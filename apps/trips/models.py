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
    ('pay_later', 'Pay Later'),
]

# Payment status choices
PAYMENT_STATUS_CHOICES = [
    ('paid', 'Paid'),
    ('unpaid', 'Unpaid'),
    ('pay_later', 'Pay Later'),
]

# Trip status choices
TRIP_STATUS_CHOICES = [
    ('scheduled', 'Scheduled'),
    ('in_route', 'In Route'),
    ('active', 'Active'),
    ('awaiting_signature', 'Awaiting Signature'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
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

    # Trip type — single or recurring parent
    trip_type = models.CharField(max_length=10, choices=TRIP_TYPE_CHOICES, default='single')

    # Parent trip — only set on recurring instances (trip_type = single, generated from recurring parent)
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

    # Requirements
    special_requirements = models.CharField(
        max_length=20, choices=SPECIAL_REQUIREMENTS_CHOICES, default='standard'
    )

    # Route info — populated from calculate-route response
    estimated_distance = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    estimated_duration = models.PositiveIntegerField(default=0)  # minutes
    route_type = models.CharField(max_length=50, blank=True)

    # Pricing
    base_fare = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    mileage_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # Payment
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')

    # Status
    status = models.CharField(max_length=25, choices=TRIP_STATUS_CHOICES, default='scheduled')

    # Timestamps for status transitions
    assigned_at = models.DateTimeField(null=True, blank=True)
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
        # Auto-generate trip_number on first save
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

            # Verify candidate is not already taken before returning
            if not Trip.objects.filter(trip_number=candidate).exists():
                return candidate

        # Fallback — use uuid-based suffix to avoid collision
        return f'TRP-{str(uuid.uuid4().int)[:6].zfill(6)}'


# Recurring trip configuration — OneToOne with parent Trip
class RecurringTripConfig(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name='recurring_config')
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)

    # Array of integers 0-6 (Monday=0) — used when frequency = weekly
    days_of_week = models.JSONField(default=list)
    end_date = models.DateField()

    # Tracks up to which date instances have been generated
    last_generated_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'recurring_trip_configs'

    def __str__(self):
        return f'Recurring config for {self.trip.trip_number}'


# Manual passenger contact for non-registered (facility-referred) passengers
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


# Passenger signature — captured by driver app at trip completion
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

    # Who triggered the change — provider, driver, system
    changed_by = models.CharField(max_length=20)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'trip_status_logs'
        ordering = ['changed_at']

    def __str__(self):
        return f'{self.trip.trip_number}: {self.from_status} → {self.to_status}'