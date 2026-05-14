from rest_framework import serializers
from apps.trips.models import Trip


# Serializer for scheduled trips (API 2 and API 3 response)
class ScheduledTripSerializer(serializers.ModelSerializer):

    passenger_name = serializers.SerializerMethodField()
    passenger_phone = serializers.SerializerMethodField()
    assigned_driver_id = serializers.SerializerMethodField()
    assigned_driver_name = serializers.SerializerMethodField()
    vehicle_id = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            'id',
            'trip_number',
            'passenger_name',
            'passenger_phone',
            'pickup_address',
            'dropoff_address',
            'pickup_date',
            'pickup_time',
            'approximate_dropoff_time',
            'assigned_driver_id',
            'assigned_driver_name',
            'vehicle_id',
            'special_requirements',
            'status',
        ]

    def get_passenger_name(self, obj):
        if obj.passenger:
            return obj.passenger.full_name
        contact = obj.passenger_contacts.first()
        return contact.full_name if contact else None

    def get_passenger_phone(self, obj):
        if obj.passenger:
            return obj.passenger.phone_number
        contact = obj.passenger_contacts.first()
        return contact.phone_number if contact else None

    def get_assigned_driver_id(self, obj):
        return str(obj.driver.id) if obj.driver else None

    def get_assigned_driver_name(self, obj):
        return obj.driver.full_name if obj.driver else None

    def get_vehicle_id(self, obj):
        return str(obj.vehicle.id) if obj.vehicle else None


# Serializer for unassigned and driver_absence trips (API 4 response)
class UnassignedTripSerializer(serializers.ModelSerializer):

    passenger_name = serializers.SerializerMethodField()
    passenger_phone = serializers.SerializerMethodField()
    assigned_driver_name = serializers.SerializerMethodField()
    vehicle_id = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            'id',
            'trip_number',
            'passenger_name',
            'passenger_phone',
            'pickup_address',
            'dropoff_address',
            'pickup_date',
            'pickup_time',
            'approximate_dropoff_time',
            'assigned_driver_name',
            'vehicle_id',
            'special_requirements',
            'status',
        ]

    def get_passenger_name(self, obj):
        if obj.passenger:
            return obj.passenger.full_name
        contact = obj.passenger_contacts.first()
        return contact.full_name if contact else None

    def get_passenger_phone(self, obj):
        if obj.passenger:
            return obj.passenger.phone_number
        contact = obj.passenger_contacts.first()
        return contact.phone_number if contact else None

    def get_assigned_driver_name(self, obj):
        return 'Unassigned'

    def get_vehicle_id(self, obj):
        return str(obj.vehicle.id) if obj.vehicle else None


# Validates the PATCH body for API 3 — at least one field required
class ScheduledTripUpdateSerializer(serializers.Serializer):

    pickup_time = serializers.TimeField(required=False)
    driver_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if not attrs.get('pickup_time') and not attrs.get('driver_id'):
            raise serializers.ValidationError(
                'At least one of pickup_time or driver_id must be provided.'
            )
        return attrs
