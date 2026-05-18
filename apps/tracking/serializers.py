from rest_framework import serializers
from .models import DriverLocation, ActiveTripTracking


# Serializes a single driver's current position for the GET /tracking/drivers/live/ response
class DriverLocationSerializer(serializers.ModelSerializer):

    driver_id = serializers.UUIDField(source='driver.id')
    full_name = serializers.CharField(source='driver.full_name')
    profile_picture = serializers.SerializerMethodField()
    status_availability = serializers.CharField(source='driver.status_availability')
    current_trip_id = serializers.SerializerMethodField()
    vehicle = serializers.SerializerMethodField()

    class Meta:
        model = DriverLocation
        fields = [
            'driver_id', 'full_name', 'profile_picture',
            'latitude', 'longitude', 'heading', 'speed',
            'timestamp', 'status_availability',
            'current_trip_id', 'vehicle',
        ]

    # Builds an absolute URL for the profile picture if one exists
    def get_profile_picture(self, obj):
        request = self.context.get('request')
        if obj.driver.profile_picture and request:
            return request.build_absolute_uri(obj.driver.profile_picture.url)
        return None

    # Returns the active trip ID when the driver is on_trip
    # active_tracking is a OneToOneField reverse — must access directly, not via .first()
    def get_current_trip_id(self, obj):
        if obj.driver.status_availability == 'on_trip':
            try:
                return str(obj.driver.active_tracking.trip.id)
            except Exception:
                pass
        return None

    # Returns basic vehicle info needed by the live map to display the correct icon
    def get_vehicle(self, obj):
        if obj.driver.vehicle:
            return {
                'vehicle_id': str(obj.driver.vehicle.id),
                'vehicle_type': obj.driver.vehicle.vehicle_type,
            }
        return None


# Serializes the full live state of an active trip for the GET /tracking/trips/{id}/live/ response
class ActiveTripTrackingSerializer(serializers.ModelSerializer):

    trip_id = serializers.UUIDField(source='trip.id')
    status = serializers.CharField(source='trip.status')
    driver = serializers.SerializerMethodField()
    passenger = serializers.SerializerMethodField()
    pickup_address = serializers.CharField(source='trip.pickup_address')
    dropoff_address = serializers.CharField(source='trip.dropoff_address')
    current_location = serializers.SerializerMethodField()
    started_at = serializers.DateTimeField(source='trip.started_at')

    class Meta:
        model = ActiveTripTracking
        fields = [
            'trip_id', 'status',
            'driver', 'passenger',
            'pickup_address', 'dropoff_address',
            'current_location', 'eta_minutes',
            'tracking_status', 'started_at',
        ]

    # Returns the driver's name, ID, and phone number for the provider's trip view
    def get_driver(self, obj):
        return {
            'full_name': obj.driver.full_name,
            'driver_id': str(obj.driver.id),
            'phone': obj.driver.phone_number,
        }

    # Returns passenger contact info — prefers the registered passenger, falls back to the manual contact
    def get_passenger(self, obj):
        trip = obj.trip
        if trip.passenger:
            return {
                'name': trip.passenger.full_name,
                'phone': trip.passenger.phone_number,
            }
        contact = trip.passenger_contacts.first()
        if contact:
            return {
                'name': contact.full_name,
                'phone': contact.phone_number,
            }
        return None

    # Returns the driver's current coordinates and when they were last updated
    def get_current_location(self, obj):
        return {
            'latitude': obj.current_lat,
            'longitude': obj.current_lng,
            'last_updated': obj.last_updated,
        }
