from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .models import (
    Passenger, PassengerMedical, PassengerEmergencyContact,
    PassengerInsurance, PassengerCommonLocation, PassengerFacility, PreferredDriver,
)
from .serializers import (
    PassengerListSerializer,
    PassengerCreateSerializer,
    PassengerHeaderSerializer,
    PassengerHeaderUpdateSerializer,
    PassengerEmergencyContactSerializer,
    PassengerCommonLocationSerializer,
    PreferredDriverSerializer,
    PassengerMedicalSerializer,
    PassengerInsuranceSerializer,
    CommonLocationUpdateSerializer,
    PassengerMedicalUpdateSerializer,
)


# List and create passengers for the authenticated provider
class PassengerListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        queryset = Passenger.objects.filter(provider=request.user).select_related('insurance')

        # Search across id, name, phone, email
        search = request.query_params.get('search')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(id__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(email__icontains=search)
            )

        # Header stats
        stats = queryset.aggregate(
            outstanding_balance=Sum('outstanding_balance'),
            total_trips=Sum('total_trips'),
        )

        header = {
            'total_passengers': queryset.count(),
            'active_passengers': queryset.filter(status='active').count(),
            'outstanding_balance': str(stats['outstanding_balance'] or '0.00'),
            'total_trips': stats['total_trips'] or 0,
        }

        serializer = PassengerListSerializer(queryset, many=True, context={'request': request})
        return CustomResponse.success(
            message='Passengers fetched successfully.',
            data={'header': header, 'passengers': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = PassengerCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate email unique within provider
        if Passenger.objects.filter(provider=request.user, email=data['email']).exists():
            return CustomResponse.error(
                message='A passenger with this email already exists under your account.',
                status_code=400
            )

        # Validate phone unique within provider
        if Passenger.objects.filter(provider=request.user, phone_number=data['phone_number']).exists():
            return CustomResponse.error(
                message='A passenger with this phone number already exists under your account.',
                status_code=400
            )

        # Validate all facility IDs belong to this provider
        facility_ids = data.get('facilities', [])
        if facility_ids:
            from apps.facilities.models import Facility
            valid_count = Facility.objects.filter(
                id__in=facility_ids, provider=request.user
            ).count()
            if valid_count != len(facility_ids):
                return CustomResponse.error(
                    message='One or more facilities do not belong to your account.',
                    status_code=400
                )

        with transaction.atomic():
            # Create passenger
            passenger = Passenger.objects.create(
                provider=request.user,
                first_name=data['first_name'],
                last_name=data['last_name'],
                date_of_birth=data.get('date_of_birth'),
                phone_number=data['phone_number'],
                email=data['email'],
                preferred_language=data.get('preferred_language', ''),
                street_address=data.get('street_address', ''),
                apartment=data.get('apartment'),
                city=data.get('city', ''),
                state=data.get('state', ''),
                zip_code=data.get('zip_code', ''),
                mobility=data.get('mobility', 'ambulatory'),
                status='active',
            )

            # Create medical record
            PassengerMedical.objects.create(
                passenger=passenger,
                special_requirements=data.get('special_requirements', 'standard'),
                medical_notes=data.get('medical_notes'),
                special_assistance_needs=data.get('special_assistance_needs'),
            )

            # Create emergency contact
            PassengerEmergencyContact.objects.create(
                passenger=passenger,
                full_name=data.get('ec_full_name', ''),
                phone_number=data.get('ec_phone_number', ''),
                email=data.get('ec_email', ''),
                relation=data.get('ec_relation', 'other'),
                home_address=data.get('ec_home_address', ''),
            )

            # Create insurance record
            PassengerInsurance.objects.create(
                passenger=passenger,
                insurance_provider=data.get('insurance_provider', ''),
                policy_number=data.get('policy_number', ''),
                medicare_number=data.get('medicare_number'),
                medicaid_number=data.get('medicaid_number'),
                effective_date=data.get('effective_date'),
                expiry_date=data.get('expiry_date'),
            )

            # Create common locations — max 2
            for loc in data.get('common_locations', []):
                PassengerCommonLocation.objects.create(
                    passenger=passenger,
                    location_name=loc['location_name'],
                    full_address=loc['full_address'],
                )

            # Create facility associations
            for facility_id in facility_ids:
                PassengerFacility.objects.create(
                    passenger=passenger,
                    facility_id=facility_id,
                )

        response_serializer = PassengerHeaderSerializer(passenger, context={'request': request})
        return CustomResponse.success(
            message='Passenger created successfully.',
            data=response_serializer.data,
            status_code=201
        )


# Retrieve or update passenger details 
class PassengerDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_passenger(self, passenger_id, provider):
        return get_object_or_404(Passenger, id=passenger_id, provider=provider)

    def get(self, request, id):
        passenger = self.get_passenger(id, request.user)
        serializer = PassengerHeaderSerializer(passenger, context={'request': request})
        return CustomResponse.success(
            message='Passenger fetched successfully.',
            data=serializer.data,
            status_code=200
        )

    def patch(self, request, id):
        passenger = self.get_passenger(id, request.user)

        # Reject read-only fields
        read_only = ['total_trips', 'completed_trips', 'total_spent', 'outstanding_balance']
        for field in read_only:
            if field in request.data:
                return CustomResponse.error(
                    message=f'Field "{field}" is read-only and cannot be updated.',
                    status_code=400
                )

        serializer = PassengerHeaderUpdateSerializer(passenger, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()

        return CustomResponse.success(
            message='Passenger updated successfully.',
            data=PassengerHeaderSerializer(passenger, context={'request': request}).data,
            status_code=200
        )


# emergency contact + common locations update view
class PassengerOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get_passenger(self, passenger_id, provider):
        return get_object_or_404(Passenger, id=passenger_id, provider=provider)

    def get(self, request, id):
        passenger = self.get_passenger(id, request.user)

        # Emergency contact
        try:
            ec = passenger.emergency_contact
            emergency_contact = {
                'full_name': ec.full_name,
                'phone_number': ec.phone_number,
                'relation': ec.relation,
            }
        except PassengerEmergencyContact.DoesNotExist:
            emergency_contact = None

        # Common locations — ordered by trips_count descending
        locations = passenger.common_locations.order_by('-trips_count')
        location_serializer = PassengerCommonLocationSerializer(locations, many=True)

        # Preferred drivers — read-only, managed by trips app
        preferred = passenger.preferred_drivers.order_by('-trips_count')
        driver_serializer = PreferredDriverSerializer(preferred, many=True, context={'request': request})

        return CustomResponse.success(
            message='Passenger overview fetched successfully.',
            data={
                'emergency_contact': emergency_contact,
                'common_locations': location_serializer.data,
                'preferred_drivers': driver_serializer.data,
            },
            status_code=200
        )

    def patch(self, request, id):
        passenger = self.get_passenger(id, request.user)

        with transaction.atomic():
            # Update emergency contact if ec fields provided
            ec_fields = ['ec_full_name', 'ec_phone_number', 'ec_email', 'ec_relation', 'ec_home_address']
            ec_data = {}
            for field in ec_fields:
                if field in request.data:
                    # Strip ec_ prefix for model field name
                    ec_data[field.replace('ec_', '')] = request.data[field]

            if ec_data:
                PassengerEmergencyContact.objects.update_or_create(
                    passenger=passenger,
                    defaults=ec_data
                )

            # Handle common location changes
            locations_data = request.data.get('common_locations', [])
            for loc_data in locations_data:
                loc_serializer = CommonLocationUpdateSerializer(data=loc_data)
                if not loc_serializer.is_valid():
                    return CustomResponse.error(
                        message='Invalid location data.',
                        status_code=400,
                        errors=loc_serializer.errors
                    )

                validated = loc_serializer.validated_data
                loc_id = validated.get('id')

                # Delete existing location
                if loc_id and validated.get('delete'):
                    PassengerCommonLocation.objects.filter(
                        id=loc_id, passenger=passenger
                    ).delete()

                # Update existing location
                elif loc_id:
                    PassengerCommonLocation.objects.filter(
                        id=loc_id, passenger=passenger
                    ).update(
                        location_name=validated.get('location_name', ''),
                        full_address=validated.get('full_address', ''),
                    )

                # Create new location
                else:
                    PassengerCommonLocation.objects.create(
                        passenger=passenger,
                        location_name=validated['location_name'],
                        full_address=validated['full_address'],
                    )

        return self.get(request, id)


# medical info + facility associations update view
class PassengerMedicalView(APIView):
    permission_classes = [IsAuthenticated]

    def get_passenger(self, passenger_id, provider):
        return get_object_or_404(Passenger, id=passenger_id, provider=provider)

    def get(self, request, id):
        passenger = self.get_passenger(id, request.user)

        # Medical info
        try:
            medical = passenger.medical
            medical_data = PassengerMedicalSerializer(medical).data
        except PassengerMedical.DoesNotExist:
            medical_data = None

        # Associated facilities
        facility_associations = passenger.facility_associations.select_related('facility')
        facilities = []
        for assoc in facility_associations:
            f = assoc.facility
            facilities.append({
                'facility_id': str(f.id),
                'facility_name': f.facility_name,
                'address': f'{f.street_address}, {f.city}, {f.state} {f.zip_code}',
            })

        return CustomResponse.success(
            message='Passenger medical info fetched successfully.',
            data={
                'medical': medical_data,
                'associated_facilities': facilities,
            },
            status_code=200
        )

    def patch(self, request, id):
        passenger = self.get_passenger(id, request.user)

        serializer = PassengerMedicalUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        with transaction.atomic():
            # Update or create medical record
            medical_fields = ['special_requirements', 'medical_notes', 'special_assistance_needs']
            medical_data = {k: data[k] for k in medical_fields if k in data}
            if medical_data:
                PassengerMedical.objects.update_or_create(
                    passenger=passenger,
                    defaults=medical_data
                )

            # Add new facility associations
            add_facilities = data.get('add_facilities', [])
            if add_facilities:
                from apps.facilities.models import Facility
                valid = Facility.objects.filter(
                    id__in=add_facilities, provider=request.user
                ).values_list('id', flat=True)

                invalid = set(str(f) for f in add_facilities) - set(str(v) for v in valid)
                if invalid:
                    return CustomResponse.error(
                        message='One or more facilities do not belong to your account.',
                        status_code=400
                    )

                for facility_id in valid:
                    PassengerFacility.objects.get_or_create(
                        passenger=passenger,
                        facility_id=facility_id
                    )

            # Remove facility associations
            remove_facilities = data.get('remove_facilities', [])
            if remove_facilities:
                PassengerFacility.objects.filter(
                    passenger=passenger,
                    facility_id__in=remove_facilities
                ).delete()

        return self.get(request, id)


# recent trips + favorite destinations view
class PassengerHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        passenger = get_object_or_404(Passenger, id=id, provider=request.user)

        # Recent trips — pulled from trips app
        # Placeholder until trips app is built — returns empty list
        recent_trips = []

        try:
            from apps.trips.models import Trip
            trip_qs = Trip.objects.filter(
                passenger=passenger,
                status='completed'
            ).select_related('driver').order_by('-pickup_date', '-pickup_time')[:10]

            for trip in trip_qs:
                recent_trips.append({
                    'invoice_id': str(trip.id),
                    'date_time': str(trip.pickup_date),
                    'driver_name': trip.driver.full_name if trip.driver else None,
                    'from_location': trip.pickup_address,
                    'to_location': trip.dropoff_address,
                    'trip_type': trip.trip_type,
                    'amount': str(trip.total_amount),
                })
        except Exception:
            # Trips app not yet available
            pass

        # Favorite destinations from common locations
        common_locs = passenger.common_locations.order_by('-trips_count')
        favorite_destinations = [
            {'destination_name': loc.location_name, 'trips_count': loc.trips_count}
            for loc in common_locs
        ]

        return CustomResponse.success(
            message='Passenger history fetched successfully.',
            data={
                'recent_trips': recent_trips,
                'favorite_destinations': favorite_destinations,
            },
            status_code=200
        )


# insurance info + payment summary view
class PassengerOthersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        passenger = get_object_or_404(Passenger, id=id, provider=request.user)

        # Insurance info
        try:
            insurance = passenger.insurance
            insurance_data = {
                'insurance_provider': insurance.insurance_provider,
                'policy_number': insurance.policy_number,
                'medicare_number': insurance.medicare_number,
                'effective_date': insurance.effective_date,
                'expiry_date': insurance.expiry_date,
            }
        except PassengerInsurance.DoesNotExist:
            insurance_data = None

        # Payment summary — paid = total_spent - outstanding_balance
        total_spent = passenger.total_spent
        outstanding = passenger.outstanding_balance
        paid = total_spent - outstanding

        return CustomResponse.success(
            message='Passenger insurance and payment info fetched successfully.',
            data={
                'insurance': insurance_data,
                'payment_summary': {
                    'total_spent': str(total_spent),
                    'paid': str(paid),
                    'outstanding_balance': str(outstanding),
                },
            },
            status_code=200
        )


# DELETE /passengers/{id}/ — permanently delete a passenger
class PassengerDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, id):
        passenger = get_object_or_404(Passenger, id=id, provider=request.user)

        # Block deletion if passenger has any active (non-terminal) trips
        try:
            from apps.trips.models import Trip
            active_trip = Trip.objects.filter(
                passenger=passenger,
                status__in=['pending', 'unassigned', 'driver_selected', 'scheduled',
                            'on_way', 'in_progress', 'awaiting_signature'],
            ).first()
            if active_trip:
                return CustomResponse.error(
                    message=(
                        f'Cannot delete a passenger with an active trip '
                        f'({active_trip.trip_number}, status: {active_trip.status}).'
                    ),
                    status_code=400
                )
        except Exception:
            pass

        passenger.delete()

        return CustomResponse.success(
            message='Passenger deleted successfully.',
            status_code=200
        )
