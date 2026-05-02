import uuid
from django.db import models
from apps.accounts.models import Provider


# Mobility type choices
MOBILITY_CHOICES = [
    ('wheelchair', 'Wheelchair'),
    ('ambulatory', 'Ambulatory'),
    ('stretcher', 'Stretcher'),
    ('oxygen', 'Oxygen'),
]

# Passenger status choices
STATUS_CHOICES = [
    ('active', 'Active'),
    ('inactive', 'Inactive'),
]

# Special requirements choices
SPECIAL_REQUIREMENTS_CHOICES = [
    ('standard', 'Standard'),
    ('stretcher', 'Stretcher'),
    ('oxygen', 'Oxygen'),
    ('wheelchair', 'Wheelchair'),
]

# Emergency contact relation choices
RELATION_CHOICES = [
    ('self', 'Self'),
    ('father', 'Father'),
    ('mother', 'Mother'),
    ('other', 'Other'),
]


# Core passenger model
class Passenger(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='passengers')

    # Personal info
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    profile_picture = models.ImageField(upload_to='passengers/profiles/', null=True, blank=True)
    preferred_language = models.CharField(max_length=50, blank=True)

    # Address
    street_address = models.CharField(max_length=255, blank=True)
    apartment = models.CharField(max_length=50, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)

    # Mobility and status
    mobility = models.CharField(max_length=20, choices=MOBILITY_CHOICES, default='ambulatory')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')

    # Denormalized stats — updated by trips and billing apps
    total_trips = models.PositiveIntegerField(default=0)
    completed_trips = models.PositiveIntegerField(default=0)
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    outstanding_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'passengers'
        # email and phone unique per provider
        unique_together = [
            ('provider', 'email'),
            ('provider', 'phone_number'),
        ]

    def __str__(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def home_address(self):
        # Compose full address string
        parts = [self.street_address]
        if self.apartment:
            parts.append(self.apartment)
        parts += [self.city, self.state, self.zip_code]
        return ', '.join(p for p in parts if p)


# Medical info — OneToOne per passenger
class PassengerMedical(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    passenger = models.OneToOneField(Passenger, on_delete=models.CASCADE, related_name='medical')
    special_requirements = models.CharField(
        max_length=20, choices=SPECIAL_REQUIREMENTS_CHOICES, default='standard'
    )
    medical_notes = models.TextField(blank=True, null=True)
    special_assistance_needs = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'passenger_medical'

    def __str__(self):
        return f'Medical for {self.passenger}'


# Emergency contact — OneToOne per passenger
class PassengerEmergencyContact(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    passenger = models.OneToOneField(Passenger, on_delete=models.CASCADE, related_name='emergency_contact')
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    relation = models.CharField(max_length=10, choices=RELATION_CHOICES, default='other')
    home_address = models.TextField(blank=True)

    class Meta:
        db_table = 'passenger_emergency_contacts'

    def __str__(self):
        return f'Emergency contact for {self.passenger}'


# Insurance info — OneToOne per passenger
class PassengerInsurance(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    passenger = models.OneToOneField(Passenger, on_delete=models.CASCADE, related_name='insurance')
    insurance_provider = models.CharField(max_length=255, blank=True)
    policy_number = models.CharField(max_length=100, blank=True)
    medicare_number = models.CharField(max_length=100, blank=True, null=True)
    medicaid_number = models.CharField(max_length=100, blank=True, null=True)
    effective_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'passenger_insurance'

    def __str__(self):
        return f'Insurance for {self.passenger}'


# Common locations — multiple per passenger
class PassengerCommonLocation(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE, related_name='common_locations')
    location_name = models.CharField(max_length=255)
    full_address = models.TextField()
    # trips_count incremented by trips app when this location is used
    trips_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'passenger_common_locations'
        ordering = ['-trips_count']

    def __str__(self):
        return f'{self.location_name} — {self.passenger}'


# M2M through table — passenger ↔ facility association
class PassengerFacility(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE, related_name='facility_associations')
    facility = models.ForeignKey(
        'facilities.Facility', on_delete=models.CASCADE, related_name='passenger_associations'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'passenger_facilities'
        unique_together = [('passenger', 'facility')]

    def __str__(self):
        return f'{self.passenger} — {self.facility}'


# Preferred drivers — auto-created by trips app only
class PreferredDriver(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE, related_name='preferred_drivers')
    driver = models.ForeignKey(
        'drivers.Driver', on_delete=models.CASCADE, related_name='preferred_by_passengers'
    )
    # trips_count updated by trips app on each completed trip together
    trips_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'preferred_drivers'
        unique_together = [('passenger', 'driver')]
        ordering = ['-trips_count']

    def __str__(self):
        return f'{self.passenger} prefers {self.driver}'