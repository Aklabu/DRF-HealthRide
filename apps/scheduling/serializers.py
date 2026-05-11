from rest_framework import serializers
from .models import DailySchedule, ScheduleSlot, AIAssignmentLog


# Driver info nested in slot response
class SlotDriverSerializer(serializers.Serializer):
    full_name = serializers.CharField()
    driver_id = serializers.UUIDField()
    phone = serializers.CharField()
    status_availability = serializers.CharField()


# Vehicle info nested in slot response
class SlotVehicleSerializer(serializers.Serializer):
    vehicle_id = serializers.UUIDField()
    vehicle_type = serializers.CharField()


# Single schedule slot — full detail for daily view
class ScheduleSlotSerializer(serializers.ModelSerializer):

    slot_id = serializers.UUIDField(source='id')
    trip_id = serializers.UUIDField(source='trip.id')
    pickup_time = serializers.TimeField(source='trip.pickup_time')
    approximate_dropoff_time = serializers.TimeField(source='trip.approximate_dropoff_time')
    passenger_name = serializers.SerializerMethodField()
    passenger_phone = serializers.SerializerMethodField()
    pickup_address = serializers.CharField(source='trip.pickup_address')
    dropoff_address = serializers.CharField(source='trip.dropoff_address')
    special_requirements = serializers.CharField(source='trip.special_requirements')
    driver = serializers.SerializerMethodField()
    vehicle = serializers.SerializerMethodField()
    trip_status = serializers.CharField(source='trip.status')
    trip_progress = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleSlot
        fields = [
            'slot_id', 'trip_id',
            'pickup_time', 'approximate_dropoff_time',
            'passenger_name', 'passenger_phone',
            'pickup_address', 'dropoff_address',
            'special_requirements',
            'driver', 'vehicle',
            'assignment_method', 'trip_status', 'trip_progress',
        ]

    def get_passenger_name(self, obj):
        if obj.trip.passenger:
            return obj.trip.passenger.full_name
        contact = obj.trip.passenger_contacts.first()
        return contact.full_name if contact else None

    def get_passenger_phone(self, obj):
        if obj.trip.passenger:
            return obj.trip.passenger.phone_number
        contact = obj.trip.passenger_contacts.first()
        return contact.phone_number if contact else None

    def get_driver(self, obj):
        if obj.driver:
            return {
                'full_name': obj.driver.full_name,
                'driver_id': str(obj.driver.id),
                'phone': obj.driver.phone_number,
                'status_availability': obj.driver.status_availability,
            }
        return None

    def get_vehicle(self, obj):
        if obj.trip.vehicle:
            return {
                'vehicle_id': str(obj.trip.vehicle.id),
                'vehicle_type': obj.trip.vehicle.vehicle_type,
            }
        return None

    def get_trip_progress(self, obj):
        """
        Compute percentage progress based on elapsed time between
        trip.started_at and trip.approximate_dropoff_time.
        Only meaningful for active/in_route trips.
        Returns 0 for scheduled/unassigned, 100 for completed/cancelled.
        """
        from django.utils import timezone
        from datetime import datetime

        trip = obj.trip

        if trip.status in ('completed',):
            return 100
        if trip.status in ('cancelled', 'scheduled', 'awaiting_signature'):
            return 0
        if trip.status not in ('active', 'in_route'):
            return 0

        if not trip.started_at or not trip.approximate_dropoff_time:
            return 0

        now = timezone.now()
        started = trip.started_at

        # Build dropoff datetime using today's date + approximate_dropoff_time
        dropoff_dt = datetime.combine(trip.pickup_date, trip.approximate_dropoff_time)
        dropoff_dt = timezone.make_aware(dropoff_dt, timezone.get_current_timezone())

        total_seconds = (dropoff_dt - started).total_seconds()
        if total_seconds <= 0:
            return 100

        elapsed = (now - started).total_seconds()
        progress = min(100, max(0, int((elapsed / total_seconds) * 100)))
        return progress


# Auto-assign request serializer
class AutoAssignRequestSerializer(serializers.Serializer):
    date = serializers.DateField(required=False, allow_null=True)
    trip_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_null=True
    )


# Manual slot reassignment serializer
class SlotReassignSerializer(serializers.Serializer):
    driver_id = serializers.UUIDField()
