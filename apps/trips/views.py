from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from decimal import Decimal
from datetime import datetime, timedelta

from utils.response import CustomResponse
from .models import Trip, TripPassengerContact, TripStatusLog
from .serializers import TripCreateSerializer, AssignDriverSerializer, TripConfirmSerializer, TripListSerializer, TripCancelSerializer
from .utils import (
    get_route_from_google_maps,
    compute_pricing_v2,
    get_available_drivers,
    find_earliest_available_driver,
    compute_dropoff_time,
    handle_trip_completion,
    stub_send_payment_link,
    stub_send_confirmation,
)


# Create a new trip with pricing calculation and driver availability check
class TripCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        serializer = TripCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        pickup = data['pickup']
        passenger_data = data['passenger']
        trip_type = data['tripType']
        special_req = pickup['specialRequirement']

        # Check rate card exists before calling Google Maps
        try:
            rate_card = request.user.rate_card
        except Exception:
            return CustomResponse.error(
                message='Rate card is not configured. Please set up your rates before creating trips.',
                status_code=400
            )

        # Google Maps route calculation
        route_result, error = get_route_from_google_maps(
            pickup['address'], pickup['dropAddress']
        )
        if error:
            return CustomResponse.error(message=error, status_code=400)

        estimated_distance = Decimal(str(route_result['estimated_distance']))
        estimated_duration = route_result['estimated_duration']

        # Server-side pricing
        pricing = compute_pricing_v2(
            estimated_distance=estimated_distance,
            special_requirements=special_req,
            rate_card=rate_card,
            trip_type=trip_type,
        )

        # Approximate dropoff time
        approx_dropoff = compute_dropoff_time(pickup['time'], estimated_duration)

        # Check driver availability before creating trip
        available_drivers = get_available_drivers(
            provider=request.user,
            special_requirements=special_req,
            pickup_date=pickup['date'],
            pickup_time=pickup['time'],
        )

        # Determine initial trip status based on driver availability
        initial_status = 'pending' if available_drivers else 'unassigned'

        # Create trip record
        with transaction.atomic():
            trip = Trip.objects.create(
                provider=request.user,
                trip_type=trip_type,
                pickup_address=pickup['address'],
                dropoff_address=pickup['dropAddress'],
                pickup_date=pickup['date'],
                pickup_time=pickup['time'],
                approximate_dropoff_time=approx_dropoff,
                pickup_notes=pickup.get('notes'),
                special_requirements=special_req,
                estimated_distance=estimated_distance,
                estimated_duration=estimated_duration,
                route_type=route_result.get('route_type', 'fastest'),
                pickup_latitude=route_result.get('pickup_latitude'),
                pickup_longitude=route_result.get('pickup_longitude'),
                dropoff_latitude=route_result.get('dropoff_latitude'),
                dropoff_longitude=route_result.get('dropoff_longitude'),
                base_fare=pricing['baseFare'],
                mileage_rate=pricing['mileageRate'],
                total_mileage_cost=pricing['totalMileageCost'],
                subtotal=pricing['subtotal'],
                trip_multiplier=pricing['tripMultiplier'],
                estimated_total=pricing['estimatedTotal'],
                status=initial_status,
            )

            # Create passenger contact record
            TripPassengerContact.objects.create(
                trip=trip,
                full_name=passenger_data['fullName'],
                phone_number=passenger_data['phone'],
                email=passenger_data.get('email', ''),
                relation=passenger_data.get('relation', 'other'),
                home_address=passenger_data.get('homeAddress', ''),
            )

            TripStatusLog.objects.create(
                trip=trip,
                from_status='',
                to_status=initial_status,
                changed_by='provider',
                notes='No drivers available at pickup time.' if initial_status == 'unassigned' else None,
            )

        contact = trip.passenger_contacts.first()

        # Prepare response message based on trip status
        if initial_status == 'unassigned':
            message = 'Trip created successfully but marked as unassigned. No drivers are available at the requested pickup time.'
        else:
            message = 'Trip created successfully.'

        return CustomResponse.success(
            message=message,
            data={
                'tripId': str(trip.id),
                'tripNumber': trip.trip_number,
                'status': trip.status,
                'route': {
                    'pickupLocation': {
                        'address': trip.pickup_address,
                        'latitude': float(trip.pickup_latitude) if trip.pickup_latitude else None,
                        'longitude': float(trip.pickup_longitude) if trip.pickup_longitude else None,
                    },
                    'dropLocation': {
                        'address': trip.dropoff_address,
                        'latitude': float(trip.dropoff_latitude) if trip.dropoff_latitude else None,
                        'longitude': float(trip.dropoff_longitude) if trip.dropoff_longitude else None,
                    },
                    'estimatedDistance': float(trip.estimated_distance),
                    'estimatedDuration': trip.estimated_duration,
                    'routeType': trip.route_type,
                },
                'pricing': {
                    'baseFare': float(trip.base_fare),
                    'mileageRate': float(trip.mileage_rate),
                    'totalMileageCost': float(trip.total_mileage_cost),
                    'subtotal': float(trip.subtotal),
                    'tripMultiplier': float(trip.trip_multiplier),
                    'estimatedTotal': float(trip.estimated_total),
                },
                'availableDrivers': available_drivers,
            },
            status_code=201
        )


# Assign a driver to a pending or unassigned trip
class TripAssignDriverView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, id):
        trip = get_object_or_404(Trip, id=id, provider=request.user)

        if trip.status not in ('pending', 'unassigned'):
            return CustomResponse.error(
                message=f'Driver selection is only allowed on pending or unassigned trips. Current status: {trip.status}.',
                status_code=400
            )

        serializer = AssignDriverSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        driver_id = data.get('driverId')
        driver_reassigned = False
        alternative_drivers = []

        from apps.drivers.models import Driver, DriverAvailability

        # Map special_requirements to vehicle type
        req_to_vehicle = {
            'standard': 'sedan',
            'oxygen': 'sedan',
            'wheelchair': 'wheelchair_accessible',
            'stretcher': 'stretcher',
        }
        required_vehicle_type = req_to_vehicle.get(trip.special_requirements, 'sedan')
        pickup_weekday = trip.pickup_date.weekday()

        def is_driver_available(driver):
            try:
                avail = DriverAvailability.objects.get(
                    driver=driver,
                    day_of_week=pickup_weekday,
                    is_available=True,
                )
                return avail.start_time <= trip.pickup_time <= avail.end_time
            except DriverAvailability.DoesNotExist:
                return False

        assigned_driver = None

        if driver_id:
            try:
                requested_driver = Driver.objects.get(id=driver_id, provider=request.user)
            except Driver.DoesNotExist:
                return CustomResponse.error(
                    message='Driver not found or does not belong to your account.',
                    status_code=404
                )

            if is_driver_available(requested_driver):
                assigned_driver = requested_driver
            else:
                # Find earliest available driver with same specialization
                assigned_driver, alternative_drivers = find_earliest_available_driver(
                    provider=request.user,
                    required_vehicle_type=required_vehicle_type,
                    exclude_driver_id=driver_id,
                )
                if not assigned_driver:
                    return CustomResponse.error(
                        message='Selected driver is unavailable and no alternative drivers found.',
                        status_code=400,
                        errors={'alternativeDrivers': alternative_drivers}
                    )
                driver_reassigned = True
        else:
            # Auto-assign highest-rated available driver
            candidates = get_available_drivers(
                provider=request.user,
                special_requirements=trip.special_requirements,
                pickup_date=trip.pickup_date,
                pickup_time=trip.pickup_time,
            )
            if not candidates:
                return CustomResponse.error(
                    message='No available drivers match the trip requirements.',
                    status_code=400
                )
            # get_available_drivers returns sorted by rating — pick first
            try:
                assigned_driver = Driver.objects.get(
                    id=candidates[0]['driverId'], provider=request.user
                )
            except Driver.DoesNotExist:
                return CustomResponse.error(
                    message='Auto-assignment failed. Please select a driver manually.',
                    status_code=400
                )

        with transaction.atomic():
            trip.driver = assigned_driver
            trip.vehicle = assigned_driver.vehicle
            trip.assigned_at = timezone.now()
            trip.authorization_number = data['authorizationNumber']
            trip.medical_notes = data.get('medicalNotes')
            trip.payment_method = data['paymentMethod']
            trip.payment_delivery = data.get('paymentDelivery')
            old_status = trip.status
            trip.status = 'driver_selected'
            trip.save()

            assigned_driver.status_availability = 'on_trip'
            assigned_driver.save(update_fields=['status_availability'])

            TripStatusLog.objects.create(
                trip=trip,
                from_status=old_status,
                to_status='driver_selected',
                changed_by='provider',
                notes=f'Driver {assigned_driver.full_name} assigned{"(reassigned)" if driver_reassigned else ""}.',
            )

        contact = trip.passenger_contacts.first()

        response_data = {
            'tripId': str(trip.id),
            'tripNumber': trip.trip_number,
            'passenger': {
                'fullName': contact.full_name if contact else None,
                'phone': contact.phone_number if contact else None,
                'email': contact.email if contact else None,
                'relation': contact.relation if contact else None,
                'homeAddress': contact.home_address if contact else None,
            },
            'tripDetails': {
                'tripType': trip.trip_type,
                'pickupDate': str(trip.pickup_date),
                'pickupTime': str(trip.pickup_time),
                'notes': trip.pickup_notes,
                'specialRequirement': trip.special_requirements,
            },
            'route': {
                'pickupLocation': {
                    'address': trip.pickup_address,
                    'latitude': float(trip.pickup_latitude) if trip.pickup_latitude else None,
                    'longitude': float(trip.pickup_longitude) if trip.pickup_longitude else None,
                },
                'dropLocation': {
                    'address': trip.dropoff_address,
                    'latitude': float(trip.dropoff_latitude) if trip.dropoff_latitude else None,
                    'longitude': float(trip.dropoff_longitude) if trip.dropoff_longitude else None,
                },
                'estimatedDistance': float(trip.estimated_distance),
                'estimatedDuration': trip.estimated_duration,
                'routeType': trip.route_type,
            },
            'pricing': {
                'baseFare': float(trip.base_fare),
                'mileageRate': float(trip.mileage_rate),
                'totalMileageCost': float(trip.total_mileage_cost),
                'subtotal': float(trip.subtotal),
                'tripMultiplier': float(trip.trip_multiplier),
                'estimatedTotal': float(trip.estimated_total),
            },
            'assignedDriver': {
                'driverId': str(assigned_driver.id),
                'name': assigned_driver.full_name,
                'rating': float(assigned_driver.on_time_rate),
                'phone': assigned_driver.phone_number,
                'vehicleType': assigned_driver.vehicle.vehicle_type if assigned_driver.vehicle else None,
                'vehicleNumber': assigned_driver.vehicle.license_plate if assigned_driver.vehicle else None,
                'pickupTime': str(trip.pickup_time),
                'availability': 'on_trip',
                'specialization': trip.special_requirements,
            },
            'authorization': {
                'authorizationNumber': trip.authorization_number,
            },
            'medicalNotes': trip.medical_notes,
            'paymentInfo': {
                'method': trip.payment_method,
                'deliveryMethod': trip.payment_delivery,
                'estimatedAmount': float(trip.estimated_total),
                'status': 'pending',
            },
        }

        if driver_reassigned:
            response_data['driverReassigned'] = True
            response_data['requestedPickupTime'] = str(trip.pickup_time)
            response_data['alternativeDrivers'] = alternative_drivers
            message = 'Selected driver was unavailable. A replacement driver has been assigned.'
        else:
            message = 'Driver assigned successfully. Please review and confirm the trip.'

        return CustomResponse.success(
            message=message,
            data=response_data,
            status_code=200
        )


# Confirm or cancel a trip after driver assignment
class TripConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, id):
        trip = get_object_or_404(Trip, id=id, provider=request.user)

        if trip.status != 'driver_selected':
            return CustomResponse.error(
                message=f'Trip confirmation is only allowed on driver_selected trips. Current status: {trip.status}.',
                status_code=400
            )
        serializer = TripConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        action = serializer.validated_data['action']
        contact = trip.passenger_contacts.first()

        if action == 'cancel':
            with transaction.atomic():
                old_status = trip.status
                trip.status = 'cancelled'
                trip.cancelled_at = timezone.now()
                trip.save(update_fields=['status', 'cancelled_at'])

                if trip.driver:
                    trip.driver.status_availability = 'available'
                    trip.driver.save(update_fields=['status_availability'])

                TripStatusLog.objects.create(
                    trip=trip,
                    from_status=old_status,
                    to_status='cancelled',
                    changed_by='provider',
                    notes='Cancelled at confirmation step.',
                )

            return CustomResponse.success(
                message='Trip cancelled successfully.',
                data={
                    'status': 'cancelled',
                    'tripId': str(trip.id),
                    'tripNumber': trip.trip_number,
                    'message': 'The trip has been cancelled and the driver has been released.',
                    'refundStatus': 'not_applicable',
                },
                status_code=200
            )

        # action == 'confirm'
        payment_link_data = None

        with transaction.atomic():
            trip.status = 'scheduled'
            trip.confirmed_at = timezone.now()

            # Generate and send payment link if send_link method
            if trip.payment_method == 'send_link':
                link_result = stub_send_payment_link(
                    trip=trip,
                    delivery_method=trip.payment_delivery,
                    contact=contact,
                )
                trip.payment_link = link_result['link']
                trip.payment_status = 'pending'
                payment_link_data = link_result
            elif trip.payment_method == 'payment_later':
                trip.payment_status = 'payment_later'
            else:
                trip.payment_status = 'unpaid'

            trip.save()

            TripStatusLog.objects.create(
                trip=trip,
                from_status='driver_selected',
                to_status='scheduled',
                changed_by='provider',
            )

        # Send confirmations — stubbed, non-blocking
        confirmation_sent = stub_send_confirmation(trip=trip, contact=contact)

        return CustomResponse.success(
            message='Trip scheduled successfully.',
            data={
                'status': 'scheduled',
                'tripId': str(trip.id),
                'bookingConfirmation': {
                    'passengerName': contact.full_name if contact else None,
                    'pickupTime': str(trip.pickup_time),
                    'pickupDate': str(trip.pickup_date),
                    'pickupAddress': trip.pickup_address,
                    'dropAddress': trip.dropoff_address,
                    'specialRequirement': trip.special_requirements,
                    'driverName': trip.driver.full_name if trip.driver else None,
                    'driverPhone': trip.driver.phone_number if trip.driver else None,
                    'vehicleNumber': trip.vehicle.license_plate if trip.vehicle else None,
                    'estimatedFare': float(trip.estimated_total),
                    'authorizationNumber': trip.authorization_number,
                },
                'paymentLink': payment_link_data,
                'confirmationSent': confirmation_sent,
            },
            status_code=200
        )

# Retrieve list of all trips with summary statistics
class TripListView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        provider = request.user
        
        # Get all trips for the provider
        trips = Trip.objects.filter(provider=provider).select_related('driver', 'vehicle').prefetch_related('passenger_contacts')
        
        # Calculate statistics
        total_trips = trips.count()
        completed_trips = trips.filter(status='completed').count()
        # Confirmed trips with a driver assigned count as scheduled
        scheduled_trips = trips.filter(status='scheduled', driver__isnull=False).count()
        # Unassigned includes: trips with no drivers at creation time + scheduled trips without a driver
        unassigned_trips = trips.filter(status='unassigned').count() + trips.filter(status='scheduled', driver__isnull=True).count()
        cancelled_trips = trips.filter(status='cancelled').count()
        driver_absence_trips = trips.filter(status='driver_absence').count()
        
        # Serialize trip data
        serializer = TripListSerializer(trips, many=True)
        
        return CustomResponse.success(
            message='Trip list retrieved successfully.',
            data={
                'header': {
                    'totalTrips': total_trips,
                    'completedTrips': completed_trips,
                    'unassignedTrips': unassigned_trips,
                    'scheduledTrips': scheduled_trips,
                    'cancelledTrips': cancelled_trips,
                    'driverAbsenceTrips': driver_absence_trips,
                },
                'trips': serializer.data,
            },
            status_code=200
        )


# Cancel a trip at any stage
class TripCancelView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, id):
        trip = get_object_or_404(Trip, id=id, provider=request.user)
        
        # Check if trip can be cancelled
        if trip.status in ('completed', 'cancelled'):
            return CustomResponse.error(
                message=f'Cannot cancel a trip with status: {trip.status}.',
                status_code=400
            )        
        serializer = TripCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        
        cancellation_reason = serializer.validated_data.get('cancellation_reason', '')
        
        with transaction.atomic():
            old_status = trip.status
            trip.status = 'cancelled'
            trip.cancelled_at = timezone.now()
            trip.cancellation_reason = cancellation_reason
            trip.save()
            
            # Release driver if assigned
            if trip.driver:
                trip.driver.status_availability = 'available'
                trip.driver.save(update_fields=['status_availability'])
            
            # Log the cancellation
            TripStatusLog.objects.create(
                trip=trip,
                from_status=old_status,
                to_status='cancelled',
                changed_by='provider',
                notes=f'Trip cancelled. Reason: {cancellation_reason}' if cancellation_reason else 'Trip cancelled.',
            )
        
        contact = trip.passenger_contacts.first()
        
        return CustomResponse.success(
            message='Trip cancelled successfully.',
            data={
                'tripId': str(trip.id),
                'tripNumber': trip.trip_number,
                'status': 'cancelled',
                'previousStatus': old_status,
                'cancelledAt': str(trip.cancelled_at),
                'cancellationReason': cancellation_reason,
                'passenger': {
                    'name': contact.full_name if contact else None,
                    'phone': contact.phone_number if contact else None,
                },
                'driverReleased': trip.driver is not None,
                'message': 'The trip has been cancelled successfully.',
            },
            status_code=200
        )


# DELETE /trips/{id}/delete — permanently delete a trip record
class TripDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, id):
        trip = get_object_or_404(Trip, id=id, provider=request.user)

        # Only allow deletion of terminal-state trips
        non_deletable = ('on_way', 'in_progress', 'awaiting_signature')
        if trip.status in non_deletable:
            return CustomResponse.error(
                message=(
                    f'Cannot delete a trip that is currently in progress '
                    f'(status: {trip.status}). Cancel the trip first.'
                ),
                status_code=400
            )

        with transaction.atomic():
            # Release driver availability if trip was scheduled with a driver
            if trip.driver and trip.status in ('pending', 'unassigned', 'driver_selected', 'scheduled'):
                trip.driver.status_availability = 'available'
                trip.driver.save(update_fields=['status_availability'])

            trip_number = trip.trip_number
            trip.delete()

        return CustomResponse.success(
            message=f'Trip {trip_number} deleted successfully.',
            status_code=200
        )
