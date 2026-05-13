import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import Provider
from apps.drivers.models import Driver
from apps.vehicles.models import Vehicle
from apps.passengers.models import Passenger
from apps.facilities.models import Facility


# Trip type choices
TRIP_TYPE_CHOICES = [
    ('single', 'Single'),
    ('recurring', 'Recurring'),
]

# Special requirements choices
SPECIAL_REQUIREMENTS_CHOICES = [
    ('standard', 'Standard'),
    ('stretcher', 'Stretcher'),
    ('oxygen', 'Oxygen'),
    ('wheelchair', 'Wheelchair'),
]

# Payment method choices
PAYMENT_METHOD_CHOICES = [
    ('cash', 'Cash'),
    ('card', 'Card'),
    ('insurance', 'Insurance'),
    ('send_link', 'Send Link'),
    ('payment_later', 'Payment Later'),
]

# Payment delivery choices
PAYMENT_DELIVERY_CHOICES = [
    ('sms', 'SMS'),
    ('email', 'Email'),
]

# Payment status choices
PAYMENT_STATUS_CHOICES = [
    ('paid', 'Paid'),
    ('unpaid', 'Unpaid'),
    ('pending', 'Pending'),
    ('payment_later', 'Payment Later'),
]

# Trip status choices — 3-step booking lifecycle
TRIP_STATUS_CHOICES = [
    ('pending', 'Pending'),               # Created in Step 1
    ('unassigned', 'Unassigned'),         # No drivers available at pickup time
    ('driver_selected', 'Driver Selected'),  # Driver assigned in Step 2
    ('confirmed', 'Confirmed'),           # Confirmed in Step 3
    ('on_way', 'On Way'),                 # Driver en route
    ('in_progress', 'In Progress'),       # Trip active
    ('completed', 'Completed'),           # Trip done
    ('cancelled', 'Cancelled'),           # Cancelled
]

# Recurring frequency choices
FREQUENCY_CHOICES = [
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
]

# Contact relation choices
RELATION_CHOICES = [
    ('self', 'Self'),
    ('father', 'Father'),
    ('mother', 'Mother'),
    ('other', 'Other'),
]


# Core trip model
class Trip(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='trips')

    # Auto-generated public-facing trip number — TRP-XXXXXX
    trip_number = models.CharField(max_length=20, unique=True, editable=False)

    # Trip type — single or recurring
    trip_type = models.CharField(max_length=10, choices=TRIP_TYPE_CHOICES, default='single')

    # Parent trip — only set on recurring instances
    parent_trip = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='recurring_instances'
    )

    # Core relations
    passenger = models.ForeignKey(
        Passenger, on_delete=models.PROTECT, null=True, blank=True, related_name='trips'
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.SET_NULL, null=True, blank=True, related_name='trips'
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='trips'
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='trips'
    )

    # Pickup and dropoff
    pickup_address = models.TextField()
    dropoff_address = models.TextField()
    pickup_date = models.DateField()
    pickup_time = models.TimeField()
    approximate_dropoff_time = models.TimeField(null=True, blank=True)
    pickup_notes = models.TextField(null=True, blank=True)

    # Route info — from Google Maps
    estimated_distance = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    estimated_duration = models.PositiveIntegerField(default=0)  # minutes
    route_type = models.CharField(max_length=50, blank=True)
    pickup_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    pickup_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    dropoff_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    dropoff_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    # Requirements
    special_requirements = models.CharField(
        max_length=20, choices=SPECIAL_REQUIREMENTS_CHOICES, default='standard'
    )

    # Pricing — computed server-side in Step 1
    base_fare = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    mileage_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    total_mileage_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    trip_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.00)
    estimated_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # Authorization & medical — stored in Step 2
    authorization_number = models.CharField(max_length=255, blank=True)
    medical_notes = models.TextField(null=True, blank=True)

    # Payment — stored in Step 2
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, null=True, blank=True)
    payment_delivery = models.CharField(max_length=10, choices=PAYMENT_DELIVERY_CHOICES, null=True, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    payment_link = models.URLField(null=True, blank=True)

    # Status
    status = models.CharField(max_length=25, choices=TRIP_STATUS_CHOICES, default='pending')

    # Timestamps
    assigned_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'trips'
        ordering = ['pickup_date', 'pickup_time']

    def __str__(self):
        return f'{self.trip_number} — {self.status}'

    def save(self, *args, **kwargs):
        if not self.trip_number:
            self.trip_number = self._generate_trip_number()
        super().save(*args, **kwargs)

    def _generate_trip_number(self):
        # Query globally — trip_number is unique across all providers
        for _ in range(10):
            existing = Trip.objects.filter(
                trip_number__startswith='TRP-'
            ).order_by('-trip_number').values_list('trip_number', flat=True).first()

            if existing:
                try:
                    last_num = int(existing.replace('TRP-', ''))
                except ValueError:
                    last_num = 0
            else:
                last_num = 0

            candidate = f'TRP-{str(last_num + 1).zfill(6)}'

            if not Trip.objects.filter(trip_number=candidate).exists():
                return candidate

        return f'TRP-{str(uuid.uuid4().int)[:6].zfill(6)}'


# Recurring trip configuration — OneToOne with parent Trip
class RecurringTripConfig(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name='recurring_config')
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    days_of_week = models.JSONField(default=list)
    end_date = models.DateField()
    last_generated_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'recurring_trip_configs'

    def __str__(self):
        return f'Recurring config for {self.trip.trip_number}'


# Manual passenger contact for unregistered passengers
class TripPassengerContact(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='passenger_contacts')
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    relation = models.CharField(max_length=10, choices=RELATION_CHOICES, default='other')
    home_address = models.TextField(blank=True)

    class Meta:
        db_table = 'trip_passenger_contacts'

    def __str__(self):
        return f'Contact {self.full_name} for {self.trip.trip_number}'


# Passenger signature — captured at trip completion
class TripSignature(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name='signature')
    signature_image = models.ImageField(upload_to='trips/signatures/')
    signed_at = models.DateTimeField()
    confirmed_by_driver = models.BooleanField(default=False)

    class Meta:
        db_table = 'trip_signatures'

    def __str__(self):
        return f'Signature for {self.trip.trip_number}'


# Immutable audit trail of all trip status changes
class TripStatusLog(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='status_logs')
    from_status = models.CharField(max_length=25)
    to_status = models.CharField(max_length=25)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.CharField(max_length=20)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'trip_status_logs'
        ordering = ['changed_at']

    def __str__(self):
        return f'{self.trip.trip_number}: {self.from_status} → {self.to_status}'