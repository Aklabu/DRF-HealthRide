import uuid
import math
from django.db import models
from apps.accounts.models import Provider
from apps.drivers.models import Driver
from apps.trips.models import Trip


# Haversine formula — calculates straight-line distance in miles between two GPS coordinates
def _haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Stores the current GPS position of each driver — one row per driver, updated in place on every location frame
class DriverLocation(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # OneToOneField enforces exactly one location record per driver at the DB level
    driver = models.OneToOneField(Driver, on_delete=models.CASCADE, related_name='location')

    # Stored here so live map queries can filter by provider without joining the driver table
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='driver_locations')

    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    timestamp = models.DateTimeField(auto_now=True)
    is_online = models.BooleanField(default=False)

    # Vehicle heading in degrees 0–360, null when stationary or unavailable
    heading = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Vehicle speed in mph, null when unavailable
    speed = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'driver_locations'

    def __str__(self):
        return f'Location for {self.driver.full_name} — online={self.is_online}'

    # Returns miles between this driver and the given coordinates — used by scheduling for proximity scoring
    def distance_to_address(self, lat, lng):
        if lat is None or lng is None:
            return 0.0
        try:
            return round(_haversine_miles(self.latitude, self.longitude, lat, lng), 2)
        except Exception:
            return 0.0


# Append-only trail of every GPS point received from a driver — written async via Celery so it never blocks the WS path
class DriverLocationHistory(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='location_history')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    timestamp = models.DateTimeField()

    # When the driver is on a trip, each history point is linked to that trip for route replay
    trip = models.ForeignKey(
        Trip, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='location_history'
    )

    class Meta:
        db_table = 'driver_location_history'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['driver', 'timestamp']),
            models.Index(fields=['trip', 'timestamp']),
        ]

    def __str__(self):
        return f'History point for {self.driver.full_name} at {self.timestamp}'


# Live tracking state for a trip in progress — created when driver starts the trip, deleted when it completes or is cancelled
class ActiveTripTracking(models.Model):

    TRACKING_STATUS_CHOICES = [
        ('en_route_to_pickup', 'En Route to Pickup'),
        ('passenger_onboard', 'Passenger Onboard'),
        ('arrived_at_dropoff', 'Arrived at Dropoff'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # One tracking record per trip — enforced at DB level
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name='active_tracking')
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='active_tracking')

    # Stored here so provider-scoped queries don't need to join through trip
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='active_trip_tracking')

    current_lat = models.DecimalField(max_digits=9, decimal_places=6)
    current_lng = models.DecimalField(max_digits=9, decimal_places=6)
    last_updated = models.DateTimeField(auto_now=True)

    # Recomputed asynchronously via Celery + Google Maps on each location update
    eta_minutes = models.PositiveIntegerField(null=True, blank=True)

    # Tracks which phase of the trip the driver is in
    status = models.CharField(
        max_length=25, choices=TRACKING_STATUS_CHOICES, default='en_route_to_pickup'
    )

    class Meta:
        db_table = 'active_trip_tracking'

    def __str__(self):
        return f'Tracking for {self.trip.trip_number} — {self.status}'
