from rest_framework import serializers
from django.utils import timezone
from datetime import datetime, timedelta
from .models import (
    Trip, RecurringTripConfig, TripPassengerContact,
    TripSignature, TripStatusLog,
)


# Trip list row serializer
class TripListSerializer(serializers.ModelSerializer):

    trip_id = serializers.UUIDField(source='id', read_only=True)
    passenger_name = serializers.SerializerMethodField()
    passenger_phone = serializers.SerializerMethodField()
    assigned_driver_name = serializers.SerializerMethodField()
    vehicle_id = serializers.SerializerMethodField()
    vehicle_type = serializers.SerializerMethodField()
    trip_status = serializers.CharField(source='status')

    class Meta:
        model = Trip
        fields = [
            'trip_id', 'pickup_date', 'pickup_time',
            'passenger_name', 'passenger_phone',
            'pickup_address', 'dropoff_address',
            'approximate_dropoff_time',
            'assigned_driver_name', 'vehicle_id', 'vehicle_type',
            'trip_status', 'payment_status', 'total_amount',
        ]

    def get_passenger_name(self, obj):
        if obj.passenger:
            return obj.passenger.full_name
        # Fall back to manual contact
        contact = obj.passenger_contacts.first()
        return contact.full_name if contact else None

    def get_passenger_phone(self, obj):
        if obj.passenger:
            return obj.passenger.phone_number
        contact = obj.passenger_contacts.first()
        return contact.phone_number if contact else None

    def get_assigned_driver_name(self, obj):
        if obj.driver:
            return obj.driver.full_name
        return None

    def get_vehicle_id(self, obj):
        if obj.vehicle:
            return str(obj.vehicle.id)
        return None

    def get_vehicle_type(self, obj):
        if obj.vehicle:
            return obj.vehicle.vehicle_type
        return None


# Route calculation request serializer — stateless
class CalculateRouteSerializer(serializers.Serializer):
    pickup_address = serializers.CharField()
    dropoff_address = serializers.CharField()

    def validate_pickup_address(self, value):
        if not value.strip():
            raise serializers.ValidationError('pickup_address must not be empty.')
        return value

    def validate_dropoff_address(self, value):
        if not value.strip():
            raise serializers.ValidationError('dropoff_address must not be empty.')
        return value


# Pricing calculation request serializer — stateless
class CalculatePricingSerializer(serializers.Serializer):
    estimated_distance = serializers.DecimalField(max_digits=8, decimal_places=2)
    special_requirements = serializers.ChoiceField(
        choices=['standard', 'stretcher', 'oxygen', 'wheelchair']
    )
    facility_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_estimated_distance(self, value):
        if value < 0:
            raise serializers.ValidationError('estimated_distance must be non-negative.')
        return value


# Recurring config nested serializer — used inside TripCreateSerializer
class RecurringConfigSerializer(serializers.Serializer):
    frequency = serializers.ChoiceField(choices=['daily', 'weekly'])
    days_of_week = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        required=False, default=list
    )
    end_date = serializers.DateField()

    def validate(self, attrs):
        if attrs['frequency'] == 'weekly' and not attrs.get('days_of_week'):
            raise serializers.ValidationError(
                {'days_of_week': 'days_of_week is required when frequency is weekly.'}
            )
        if attrs['end_date'] <= timezone.now().date():
            raise serializers.ValidationError({'end_date': 'end_date must be in the future.'})
        return attrs


# Manual passenger contact nested serializer
class PassengerContactSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)
    relation = serializers.ChoiceField(choices=['self', 'father', 'mother', 'other'], default='other')
    home_address = serializers.CharField(required=False, allow_blank=True)


# Trip creation serializer
class TripCreateSerializer(serializers.Serializer):

    trip_type = serializers.ChoiceField(choices=['single', 'recurring'], default='single')

    # Passenger — one of passenger_id or passenger_contact
    passenger_id = serializers.UUIDField(required=False, allow_null=True)
    passenger_contact = PassengerContactSerializer(required=False, allow_null=True)
    from_facility = serializers.UUIDField(required=False, allow_null=True)

    # Pickup details
    pickup_address = serializers.CharField()
    dropoff_address = serializers.CharField()
    pickup_date = serializers.DateField()
    pickup_time = serializers.TimeField()
    pickup_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    special_requirements = serializers.ChoiceField(
        choices=['standard', 'stretcher', 'oxygen', 'wheelchair'], default='standard'
    )

    # Route — from calculate-route response
    estimated_distance = serializers.DecimalField(max_digits=8, decimal_places=2)
    estimated_duration = serializers.IntegerField(min_value=0)
    route_type = serializers.CharField(max_length=50, required=False, allow_blank=True)

    # Pricing — from calculate-pricing response
    base_fare = serializers.DecimalField(max_digits=8, decimal_places=2)
    mileage_cost = serializers.DecimalField(max_digits=8, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2)

    # Payment
    payment_method = serializers.ChoiceField(choices=['cash', 'card', 'insurance', 'pay_later'])

    # Recurring config — required if trip_type = recurring
    recurring = RecurringConfigSerializer(required=False, allow_null=True)

    def validate_pickup_date(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError('pickup_date cannot be in the past.')
        return value

    def validate(self, attrs):
        # Exactly one passenger source required
        has_passenger_id = bool(attrs.get('passenger_id'))
        has_passenger_contact = bool(attrs.get('passenger_contact'))

        if not has_passenger_id and not has_passenger_contact:
            raise serializers.ValidationError(
                'Either passenger_id or passenger_contact must be provided.'
            )
        if has_passenger_id and has_passenger_contact:
            raise serializers.ValidationError(
                'Provide either passenger_id or passenger_contact, not both.'
            )

        # Recurring config required for recurring trips
        if attrs['trip_type'] == 'recurring' and not attrs.get('recurring'):
            raise serializers.ValidationError(
                {'recurring': 'Recurring config is required for recurring trips.'}
            )

        # end_date must be after pickup_date for recurring trips
        if attrs.get('recurring') and attrs['trip_type'] == 'recurring':
            if attrs['recurring']['end_date'] <= attrs['pickup_date']:
                raise serializers.ValidationError(
                    {'recurring': {'end_date': 'end_date must be after pickup_date.'}}
                )

        return attrs


# Driver assignment serializer
class AssignDriverSerializer(serializers.Serializer):
    driver_id = serializers.UUIDField()


# Status update serializer
class TripStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=['in_route', 'active', 'awaiting_signature', 'completed', 'cancelled']
    )
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


# Signature submission serializer
class TripSignatureSerializer(serializers.Serializer):
    signature_image = serializers.ImageField()
    confirmed_by_driver = serializers.BooleanField()

    def validate_confirmed_by_driver(self, value):
        if not value:
            raise serializers.ValidationError(
                'Signature must be confirmed by driver before submission.'
            )
        return value


# Status log entry serializer — read only
class TripStatusLogSerializer(serializers.ModelSerializer):

    class Meta:
        model = TripStatusLog
        fields = ['from_status', 'to_status', 'changed_at', 'changed_by', 'notes']


# Full trip detail serializer — GET /trips/{id}/
class TripDetailSerializer(serializers.ModelSerializer):

    trip_id = serializers.UUIDField(source='id', read_only=True)
    passenger = serializers.SerializerMethodField()
    facility = serializers.SerializerMethodField()
    driver = serializers.SerializerMethodField()
    vehicle = serializers.SerializerMethodField()
    pickup = serializers.SerializerMethodField()
    route = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()
    signature = serializers.SerializerMethodField()
    status_log = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            'trip_id', 'trip_type', 'status', 'payment_status',
            'special_requirements',
            'passenger', 'facility', 'driver', 'vehicle',
            'pickup', 'route', 'pricing',
            'signature', 'status_log', 'created_at',
        ]

    def get_passenger(self, obj):
        if obj.passenger:
            return {
                'name': obj.passenger.full_name,
                'phone': obj.passenger.phone_number,
                'email': obj.passenger.email,
                'mobility': obj.passenger.mobility,
            }
        # Manual contact fallback
        contact = obj.passenger_contacts.first()
        if contact:
            return {
                'name': contact.full_name,
                'phone': contact.phone_number,
                'email': contact.email,
                'mobility': None,
            }
        return None

    def get_facility(self, obj):
        if obj.facility:
            return {
                'facility_name': obj.facility.facility_name,
                'facility_id': obj.facility.facility_id,
            }
        return None

    def get_driver(self, obj):
        if obj.driver:
            return {
                'full_name': obj.driver.full_name,
                'driver_id': str(obj.driver.id),
                'phone': obj.driver.phone_number,
            }
        return None

    def get_vehicle(self, obj):
        if obj.vehicle:
            return {
                'vehicle_id': str(obj.vehicle.id),
                'vehicle_type': obj.vehicle.vehicle_type,
                'license_plate': obj.vehicle.license_plate,
            }
        return None

    def get_pickup(self, obj):
        return {
            'address': obj.pickup_address,
            'date': obj.pickup_date,
            'time': obj.pickup_time,
            'notes': obj.pickup_notes,
            'approximate_dropoff_time': obj.approximate_dropoff_time,
        }

    def get_route(self, obj):
        return {
            'estimated_distance': obj.estimated_distance,
            'estimated_duration': obj.estimated_duration,
            'route_type': obj.route_type,
        }

    def get_pricing(self, obj):
        return {
            'base_fare': obj.base_fare,
            'mileage_cost': obj.mileage_cost,
            'total_amount': obj.total_amount,
            'payment_method': obj.payment_method,
        }

    def get_signature(self, obj):
        try:
            sig = obj.signature
            return {
                'signed_at': sig.signed_at,
                'confirmed': sig.confirmed_by_driver,
            }
        except TripSignature.DoesNotExist:
            return None

    def get_status_log(self, obj):
        logs = obj.status_logs.order_by('changed_at')
        return TripStatusLogSerializer(logs, many=True).data