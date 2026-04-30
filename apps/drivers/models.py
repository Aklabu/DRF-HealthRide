import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import Provider


# Employment status choices
EMPLOYMENT_STATUS_CHOICES = [
    ('active', 'Active'),
    ('on_leave', 'On Leave'),
]

# Availability status choices
AVAILABILITY_STATUS_CHOICES = [
    ('on_trip', 'On Trip'),
    ('available', 'Available'),
    ('break', 'Break'),
    ('off_duty', 'Off Duty'),
]

# Certification type choices
CERT_TYPE_CHOICES = [
    ('cpr', 'CPR'),
    ('first_aid', 'First Aid'),
    ('wheelchair_assistance', 'Wheelchair Assistance'),
    ('defensive_driving', 'Defensive Driving'),
]

# Document type choices
DOCUMENT_TYPE_CHOICES = [
    ('driver_license', 'Driver License'),
    ('insurance', 'Insurance'),
    ('cpr_certificate', 'CPR Certificate'),
    ('background_check', 'Background Check'),
]

# Day of week choices
DAY_OF_WEEK_CHOICES = [
    (0, 'Monday'),
    (1, 'Tuesday'),
    (2, 'Wednesday'),
    (3, 'Thursday'),
    (4, 'Friday'),
    (5, 'Saturday'),
    (6, 'Sunday'),
]

# Work log status choices
WORK_LOG_STATUS_CHOICES = [
    ('worked', 'Worked'),
    ('off_day', 'Off Day'),
]


# Core driver model
class Driver(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='drivers')

    # Personal info
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    home_address = models.TextField(blank=True)
    profile_picture = models.ImageField(upload_to='drivers/profiles/', null=True, blank=True)

    # Password — hashed, set at creation via generated password
    password = models.CharField(max_length=255)

    # Status
    status_employment = models.CharField(
        max_length=20, choices=EMPLOYMENT_STATUS_CHOICES, default='active'
    )
    status_availability = models.CharField(
        max_length=20, choices=AVAILABILITY_STATUS_CHOICES, default='off_duty'
    )

    # Vehicle FK — nullable, bidirectional with Vehicle.assigned_driver
    vehicle = models.ForeignKey(
        'vehicles.Vehicle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='driver_set'
    )

    # Employment info
    joined_date = models.DateField(auto_now_add=True)
    last_active = models.DateTimeField(null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    # Denormalized stats — updated by trips app
    total_trips = models.PositiveIntegerField(default=0)
    on_time_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'drivers'

    def __str__(self):
        return f'{self.full_name} ({self.email})'


# Driver license — OneToOne per driver
class DriverLicense(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.OneToOneField(Driver, on_delete=models.CASCADE, related_name='license')
    license_number = models.CharField(max_length=100, unique=True)
    license_state = models.CharField(max_length=50)
    license_expiry_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'driver_licenses'

    def __str__(self):
        return f'License for {self.driver.full_name}'


# Emergency contact — OneToOne per driver
class DriverEmergencyContact(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.OneToOneField(Driver, on_delete=models.CASCADE, related_name='emergency_contact')
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    relationship = models.CharField(max_length=100)

    class Meta:
        db_table = 'driver_emergency_contacts'

    def __str__(self):
        return f'Emergency contact for {self.driver.full_name}'


# Certifications — one per cert_type per driver
class DriverCertification(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='certifications')
    cert_type = models.CharField(max_length=30, choices=CERT_TYPE_CHOICES)
    expiry_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'driver_certifications'
        unique_together = [('driver', 'cert_type')]

    def __str__(self):
        return f'{self.cert_type} — {self.driver.full_name}'


# Documents — history preserved, multiple per driver per type
class DriverDocument(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='drivers/documents/')
    upload_date = models.DateField(auto_now_add=True)
    expire_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'driver_documents'
        ordering = ['-upload_date']

    def __str__(self):
        return f'{self.document_type} — {self.driver.full_name}'


# Weekly availability schedule — exactly 7 records per driver
class DriverAvailability(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='availability')
    day_of_week = models.IntegerField(choices=DAY_OF_WEEK_CHOICES)
    is_available = models.BooleanField(default=False)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    class Meta:
        db_table = 'driver_availability'
        unique_together = [('driver', 'day_of_week')]
        ordering = ['day_of_week']

    def __str__(self):
        return f'{self.driver.full_name} — Day {self.day_of_week}'


# Work log — one per driver per day, managed by trips app
class DriverWorkLog(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='work_logs')
    date = models.DateField()
    hours_worked = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    trips_completed = models.PositiveIntegerField(default=0)
    earnings = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=10, choices=WORK_LOG_STATUS_CHOICES, default='off_day')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'driver_work_logs'
        unique_together = [('driver', 'date')]
        ordering = ['-date']

    def save(self, *args, **kwargs):
        # Auto-compute earnings from hours × hourly_rate
        self.earnings = self.hours_worked * self.driver.hourly_rate
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.driver.full_name} — {self.date}'


# Payout records — manual payout entries by provider
class DriverPayout(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='payouts')
    from_date = models.DateField()
    to_date = models.DateField()
    total_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'driver_payouts'
        ordering = ['-created_at']

    def __str__(self):
        return f'Payout for {self.driver.full_name} ({self.from_date} to {self.to_date})'