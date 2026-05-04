from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from decimal import Decimal
from datetime import datetime, timedelta

from utils.response import CustomResponse
from .models import (
    Trip, RecurringTripConfig, TripPassengerContact,
    TripSignature, TripStatusLog,
)
from .serializers import (
    TripListSerializer,
    TripDetailSerializer,
    TripCreateSerializer,
    TripStatusUpdateSerializer,
    AssignDriverSerializer,
    TripSignatureSerializer,
    CalculateRouteSerializer,
    CalculatePricingSerializer,
)
from .utils import (
    get_route_from_google_maps,
    compute_pricing,
    validate_pricing_match,
    compute_dropoff_time,
    generate_recurring_dates,
    attempt_auto_assignment,
    handle_trip_completion,
)


# Valid status transition map
VALID_TRANSITIONS = {
    'scheduled': ['in_route', 'cancelled'],
    'in_route': ['active', 'cancelled'],
    'active': ['awaiting_signature'],
    'awaiting_signature': ['completed'],
    'completed': [],
    'cancelled': [],
}


# Create and list trips
class TripListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        queryset = Trip.objects.filter(
            provider=request.user,
            parent_trip__isnull=True  # exclude recurring child instances from list
        ).select_related('passenger', 'driver', 'vehicle', 'facility')

        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by date
        date_filter = request.query_params.get('date')
        if date_filter:
            queryset = queryset.filter(pickup_date=date_filter)

        # Filter by driver
        driver_filter = request.query_params.get('driver_id')
        if driver_filter:
            queryset = queryset.filter(driver__id=driver_filter)

        # Filter by vehicle type
        vehicle_type_filter = request.query_params.get('vehicle_type')
        if vehicle_type_filter:
            queryset = queryset.filter(vehicle__vehicle_type=vehicle_type_filter)

        # Search by passenger name, pickup_address, or trip_number
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(trip_number__icontains=search) |
                Q(pickup_address__icontains=search) |
                Q(passenger__first_name__icontains=search) |
                Q(passenger__last_name__icontains=search)
            )

        # Header stats computed on full unfiltered provider queryset
        all_trips = Trip.objects.filter(provider=request.user, parent_trip__isnull=True)
        header = {
            'total_trips': all_trips.count(),
            'completed_trips': all_trips.filter(status='completed').count(),
            'unassigned_trips': all_trips.filter(driver__isnull=True, status='scheduled').count(),
            'scheduled_trips': all_trips.filter(status='scheduled').count(),
            'cancelled_trips': all_trips.filter(status='cancelled').count(),
        }

        serializer = TripListSerializer(queryset, many=True)
        return CustomResponse.success(
            message='Trips fetched successfully.',
            data={'header': header, 'trips': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = TripCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate passenger belongs to provider
        passenger = None
        if data.get('passenger_id'):
            from apps.passengers.models import Passenger
            try:
                passenger = Passenger.objects.get(id=data['passenger_id'], provider=request.user)
            except Passenger.DoesNotExist:
                return CustomResponse.error(
                    message='Passenger not found or does not belong to your account.',
                    status_code=404
                )

        # Validate facility belongs to provider
        facility = None
        if data.get('from_facility'):
            from apps.facilities.models import Facility
            try:
                facility = Facility.objects.get(id=data['from_facility'], provider=request.user)
            except Facility.DoesNotExist:
                return CustomResponse.error(
                    message='Facility not found or does not belong to your account.',
                    status_code=404
                )

        # Validate pickup_time against provider lead_time setting
        try:
            provider_settings = request.user.settings
            lead_minutes = provider_settings.default_trip_lead_time
            now = timezone.now()
            pickup_dt = datetime.combine(data['pickup_date'], data['pickup_time'])
            pickup_dt = timezone.make_aware(pickup_dt, timezone.get_current_timezone())
            if (pickup_dt - now).total_seconds() < lead_minutes * 60:
                return CustomResponse.error(
                    message=f'Pickup time must be at least {lead_minutes} minutes from now.',
                    status_code=400
                )
        except Exception:
            pass

        # Soft check — warn if requirements mismatch passenger medical
        requirements_warning = None
        if passenger:
            try:
                med = passenger.medical
                if med.special_requirements != data['special_requirements']:
                    requirements_warning = (
                        f'Note: passenger special requirements ({med.special_requirements}) '
                        f'differ from trip requirements ({data["special_requirements"]}).'
                    )
            except Exception:
                pass

        # Server-side pricing re-validation — prevent client-side fare manipulation
        computed = compute_pricing(
            data['estimated_distance'],
            data['special_requirements'],
            request.user,
            facility=facility,
        )
        pricing_errors = validate_pricing_match(
            data['base_fare'], data['mileage_cost'], data['total_amount'], computed
        )
        if pricing_errors:
            return CustomResponse.error(
                message='Pricing mismatch detected. Please recalculate pricing.',
                status_code=400,
                errors=pricing_errors
            )

        # Determine payment_status from payment_method
        payment_status = 'pay_later' if data['payment_method'] == 'pay_later' else 'unpaid'

        # Compute approximate dropoff time
        approx_dropoff = compute_dropoff_time(data['pickup_time'], data['estimated_duration'])

        with transaction.atomic():
            # Create the parent trip record
            trip = Trip.objects.create(
                provider=request.user,
                trip_type=data['trip_type'],
                passenger=passenger,
                facility=facility,
                pickup_address=data['pickup_address'],
                dropoff_address=data['dropoff_address'],
                pickup_date=data['pickup_date'],
                pickup_time=data['pickup_time'],
                approximate_dropoff_time=approx_dropoff,
                pickup_notes=data.get('pickup_notes'),
                special_requirements=data['special_requirements'],
                estimated_distance=data['estimated_distance'],
                estimated_duration=data['estimated_duration'],
                route_type=data.get('route_type', ''),
                base_fare=data['base_fare'],
                mileage_cost=data['mileage_cost'],
                total_amount=data['total_amount'],
                payment_method=data['payment_method'],
                payment_status=payment_status,
                status='scheduled',
            )

            # Create manual passenger contact if no registered passenger
            if data.get('passenger_contact'):
                contact = data['passenger_contact']
                TripPassengerContact.objects.create(
                    trip=trip,
                    full_name=contact['full_name'],
                    phone_number=contact['phone_number'],
                    email=contact.get('email', ''),
                    relation=contact.get('relation', 'other'),
                    home_address=contact.get('home_address', ''),
                )

            # Create status log entry — initial scheduled status
            TripStatusLog.objects.create(
                trip=trip,
                from_status='',
                to_status='scheduled',
                changed_by='provider',
            )

            # Handle recurring trip config and generate instances
            if data['trip_type'] == 'recurring' and data.get('recurring'):
                rec = data['recurring']
                config = RecurringTripConfig.objects.create(
                    trip=trip,
                    frequency=rec['frequency'],
                    days_of_week=rec.get('days_of_week', []),
                    end_date=rec['end_date'],
                    last_generated_date=rec['end_date'],
                )

                # Generate individual trip instances
                instance_dates = generate_recurring_dates(
                    data['pickup_date'],
                    rec['end_date'],
                    rec['frequency'],
                    rec.get('days_of_week', []),
                )

                # Skip first date — parent trip already covers it
                for trip_date in instance_dates[1:]:
                    instance_approx = compute_dropoff_time(data['pickup_time'], data['estimated_duration'])
                    instance = Trip.objects.create(
                        provider=request.user,
                        trip_type='single',
                        parent_trip=trip,
                        passenger=passenger,
                        facility=facility,
                        pickup_address=data['pickup_address'],
                        dropoff_address=data['dropoff_address'],
                        pickup_date=trip_date,
                        pickup_time=data['pickup_time'],
                        approximate_dropoff_time=instance_approx,
                        pickup_notes=data.get('pickup_notes'),
                        special_requirements=data['special_requirements'],
                        estimated_distance=data['estimated_distance'],
                        estimated_duration=data['estimated_duration'],
                        route_type=data.get('route_type', ''),
                        base_fare=data['base_fare'],
                        mileage_cost=data['mileage_cost'],
                        total_amount=data['total_amount'],
                        payment_method=data['payment_method'],
                        payment_status=payment_status,
                        status='scheduled',
                    )
                    TripStatusLog.objects.create(
                        trip=instance,
                        from_status='',
                        to_status='scheduled',
                        changed_by='system',
                    )

            # Attempt auto-assignment
            assigned_driver, assigned_vehicle = attempt_auto_assignment(trip, request.user)
            if assigned_driver:
                trip.driver = assigned_driver
                trip.vehicle = assigned_vehicle
                trip.assigned_at = timezone.now()
                trip.save(update_fields=['driver', 'vehicle', 'assigned_at'])

                assigned_driver.status_availability = 'on_trip'
                assigned_driver.save(update_fields=['status_availability'])

                TripStatusLog.objects.create(
                    trip=trip,
                    from_status='scheduled',
                    to_status='scheduled',
                    changed_by='system',
                    notes=f'Auto-assigned to driver {assigned_driver.full_name}',
                )

                # Notify driver — graceful fallback
                try:
                    from apps.notifications.utils import notify_driver_assignment
                    notify_driver_assignment(trip, assigned_driver)
                except Exception:
                    pass

        response_serializer = TripDetailSerializer(trip)
        response_data = response_serializer.data
        if requirements_warning:
            response_data['warning'] = requirements_warning

        return CustomResponse.success(
            message='Trip created successfully.',
            data=response_data,
            status_code=201
        )


# Stateless utility endpoints for route calculation and pricing calculation
class CalculateRouteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CalculateRouteSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        result, error = get_route_from_google_maps(
            data['pickup_address'], data['dropoff_address']
        )

        if error:
            return CustomResponse.error(message=error, status_code=400)

        return CustomResponse.success(
            message='Route calculated successfully.',
            data=result,
            status_code=200
        )


# Stateless pricing calculation
class CalculatePricingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CalculatePricingSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Resolve facility if provided
        facility = None
        if data.get('facility_id'):
            from apps.facilities.models import Facility
            try:
                facility = Facility.objects.get(id=data['facility_id'], provider=request.user)
            except Facility.DoesNotExist:
                return CustomResponse.error(
                    message='Facility not found or does not belong to your account.',
                    status_code=404
                )

        result = compute_pricing(
            data['estimated_distance'],
            data['special_requirements'],
            request.user,
            facility=facility,
        )

        return CustomResponse.success(
            message='Pricing calculated successfully.',
            data=result,
            status_code=200
        )


# Full trip detail view with related entities
class TripDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        trip = get_object_or_404(Trip, id=id, provider=request.user)
        serializer = TripDetailSerializer(trip)
        return CustomResponse.success(
            message='Trip fetched successfully.',
            data=serializer.data,
            status_code=200
        )


# Status update endpoint with strict transition rules
class TripStatusUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        trip = get_object_or_404(Trip, id=id, provider=request.user)

        serializer = TripStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        new_status = serializer.validated_data['status']
        notes = serializer.validated_data.get('notes')
        current_status = trip.status

        # Enforce valid transitions
        allowed = VALID_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            return CustomResponse.error(
                message=f'Cannot transition from "{current_status}" to "{new_status}".',
                status_code=400
            )

        with transaction.atomic():
            old_status = trip.status

            if new_status == 'in_route':
                # Driver must be assigned
                if not trip.driver:
                    return CustomResponse.error(
                        message='Cannot mark in_route — no driver assigned to this trip.',
                        status_code=400
                    )
                trip.status = 'in_route'
                trip.driver.status_availability = 'on_trip'
                trip.driver.save(update_fields=['status_availability'])

            elif new_status == 'active':
                trip.started_at = timezone.now()
                trip.status = 'active'

            elif new_status == 'awaiting_signature':
                trip.status = 'awaiting_signature'
                # Notify driver app to show signature screen
                try:
                    from apps.notifications.utils import notify_signature_required
                    notify_signature_required(trip)
                except Exception:
                    pass

            elif new_status == 'completed':
                # Completed is only triggered internally via signature endpoint
                trip.completed_at = timezone.now()
                trip.status = 'completed'
                if trip.driver:
                    trip.driver.status_availability = 'available'
                    trip.driver.save(update_fields=['status_availability'])
                handle_trip_completion(trip)

            elif new_status == 'cancelled':
                if trip.status in ('completed',):
                    return CustomResponse.error(
                        message='Cannot cancel a completed trip.',
                        status_code=400
                    )
                trip.cancelled_at = timezone.now()
                trip.cancellation_reason = notes
                trip.status = 'cancelled'

                # Free up driver
                if trip.driver:
                    trip.driver.status_availability = 'available'
                    trip.driver.save(update_fields=['status_availability'])
                    trip.driver = None
                    trip.vehicle = None

                # Flag cancellation fee to billing app if within window
                try:
                    provider_settings = request.user.settings
                    now = timezone.now()
                    pickup_dt = datetime.combine(trip.pickup_date, trip.pickup_time)
                    pickup_dt = timezone.make_aware(pickup_dt, timezone.get_current_timezone())
                    hours_until = (pickup_dt - now).total_seconds() / 3600
                    if hours_until < provider_settings.cancellation_window:
                        from apps.billing.utils import flag_cancellation_fee
                        flag_cancellation_fee(trip, provider_settings.cancellation_fee)
                except Exception:
                    pass

            trip.save()

            TripStatusLog.objects.create(
                trip=trip,
                from_status=old_status,
                to_status=new_status,
                changed_by='provider',
                notes=notes,
            )

        serializer = TripDetailSerializer(trip)
        return CustomResponse.success(
            message=f'Trip status updated to {new_status}.',
            data={
                'status': trip.status,
                'status_log': serializer.data['status_log'],
            },
            status_code=200
        )


# Manual driver assignment endpoint with validation
class TripAssignDriverView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        trip = get_object_or_404(Trip, id=id, provider=request.user)

        # Only allow assignment on scheduled trips
        if trip.status != 'scheduled':
            return CustomResponse.error(
                message='Driver can only be assigned to scheduled trips.',
                status_code=400
            )

        serializer = AssignDriverSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        driver_id = serializer.validated_data['driver_id']

        from apps.drivers.models import Driver
        try:
            driver = Driver.objects.get(id=driver_id, provider=request.user)
        except Driver.DoesNotExist:
            return CustomResponse.error(
                message='Driver not found or does not belong to your account.',
                status_code=404
            )

        # Driver must be available
        if driver.status_availability == 'on_trip':
            return CustomResponse.error(
                message='Driver is currently on another trip.',
                status_code=400
            )

        # Validate vehicle type matches trip requirements
        req_to_vehicle = {
            'standard': 'sedan',
            'oxygen': 'sedan',
            'wheelchair': 'wheelchair_accessible',
            'stretcher': 'stretcher',
        }
        required_type = req_to_vehicle.get(trip.special_requirements, 'sedan')

        if not driver.vehicle:
            return CustomResponse.error(
                message='Driver has no vehicle assigned.',
                status_code=400
            )
        if driver.vehicle.vehicle_type != required_type:
            return CustomResponse.error(
                message=f'Driver vehicle type ({driver.vehicle.vehicle_type}) does not match '
                        f'trip requirement ({required_type}).',
                status_code=400
            )

        with transaction.atomic():
            # Clear previous driver if any
            if trip.driver and trip.driver != driver:
                prev_driver = trip.driver
                prev_driver.status_availability = 'available'
                prev_driver.save(update_fields=['status_availability'])

            trip.driver = driver
            trip.vehicle = driver.vehicle
            trip.assigned_at = timezone.now()
            trip.save(update_fields=['driver', 'vehicle', 'assigned_at'])

            driver.status_availability = 'on_trip'
            driver.save(update_fields=['status_availability'])

            TripStatusLog.objects.create(
                trip=trip,
                from_status=trip.status,
                to_status=trip.status,
                changed_by='provider',
                notes=f'Manually assigned driver {driver.full_name}',
            )

            # Notify driver
            try:
                from apps.notifications.utils import notify_driver_assignment
                notify_driver_assignment(trip, driver)
            except Exception:
                pass

        return CustomResponse.success(
            message='Driver assigned successfully.',
            data={
                'trip_id': str(trip.id),
                'assigned_driver': {
                    'full_name': driver.full_name,
                    'driver_id': str(driver.id),
                },
                'assigned_vehicle': {
                    'vehicle_id': str(driver.vehicle.id),
                    'vehicle_type': driver.vehicle.vehicle_type,
                },
                'assigned_at': trip.assigned_at,
            },
            status_code=200
        )


# Driver submits passenger signature
class TripSignatureView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, id):
        # Auth here is driver — scoped by driver model, not provider
        # For now assumes driver is authenticated via JWT issued by driver_app
        trip = get_object_or_404(Trip, id=id)

        # Validate trip is in awaiting_signature state
        if trip.status != 'awaiting_signature':
            return CustomResponse.error(
                message='Signature can only be submitted when trip is awaiting_signature.',
                status_code=400
            )

        serializer = TripSignatureSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        with transaction.atomic():
            # Save signature record
            signature = TripSignature.objects.create(
                trip=trip,
                signature_image=data['signature_image'],
                signed_at=timezone.now(),
                confirmed_by_driver=data['confirmed_by_driver'],
            )

            # Trigger completion
            old_status = trip.status
            trip.completed_at = timezone.now()
            trip.status = 'completed'
            trip.save(update_fields=['status', 'completed_at'])

            if trip.driver:
                trip.driver.status_availability = 'available'
                trip.driver.save(update_fields=['status_availability'])

            TripStatusLog.objects.create(
                trip=trip,
                from_status=old_status,
                to_status='completed',
                changed_by='driver',
                notes='Trip completed after passenger signature confirmed.',
            )

            handle_trip_completion(trip)

        return CustomResponse.success(
            message='Signature submitted and trip completed.',
            data={
                'trip_id': str(trip.id),
                'trip_number': trip.trip_number,
                'status': 'completed',
                'signature': {
                    'signed_at': signature.signed_at,
                    'confirmed_by_driver': signature.confirmed_by_driver,
                },
                'completed_at': trip.completed_at,
            },
            status_code=200
        )