import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import Provider


# Vehicle type choices
VEHICLE_TYPE_CHOICES = [
    ('sedan', 'Sedan'),
    ('wheelchair_accessible', 'Wheelchair Accessible'),
    ('stretcher', 'Stretcher'),
]

# Accessibility feature choices
ACCESSIBILITY_CHOICES = [
    ('standard', 'Standard'),
    ('stretcher', 'Stretcher'),
    ('oxygen', 'Oxygen'),
    ('wheelchair', 'Wheelchair'),
]

# Ramp type choices
RAMP_TYPE_CHOICES = [
    ('fold_out', 'Fold Out'),
    ('roll_out', 'Roll Out'),
    ('none', 'None'),
]

# Vehicle status choices
STATUS_CHOICES = [
    ('active', 'Active'),
    ('inactive', 'Inactive'),
    ('in_maintenance', 'In Maintenance'),
    ('on_trip', 'On Trip'),
]

# Document type choices
DOCUMENT_TYPE_CHOICES = [
    ('registration', 'Registration'),
    ('insurance', 'Insurance'),
    ('inspection', 'Inspection'),
    ('other', 'Other'),
]


# Core vehicle model
class Vehicle(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='vehicles')

    # Basic info
    brand = models.CharField(max_length=100)
    model_number = models.CharField(max_length=100)
    year = models.PositiveIntegerField()
    color = models.CharField(max_length=50)
    license_plate = models.CharField(max_length=20)
    vin_number = models.CharField(max_length=17, unique=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    purchase_date = models.DateField(null=True, blank=True)

    # Vehicle features
    vehicle_type = models.CharField(max_length=30, choices=VEHICLE_TYPE_CHOICES)
    seating_capacity = models.PositiveIntegerField(default=4)
    accessibility_features = models.CharField(max_length=20, choices=ACCESSIBILITY_CHOICES, default='standard')
    ramp_type = models.CharField(max_length=20, choices=RAMP_TYPE_CHOICES, default='none')
    securement_system = models.CharField(max_length=255, blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    # Registration
    registration_state = models.CharField(max_length=50, blank=True)
    registration_expiry = models.DateField(null=True, blank=True)

    # Inspection — set by compliance only, never by user
    last_inspection = models.DateField(null=True, blank=True)
    next_due = models.DateField(null=True, blank=True)
    inspector = models.CharField(max_length=255, blank=True)

    # Driver assignment
    assigned_driver = models.ForeignKey(
        'drivers.Driver',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_vehicle_set'
    )
    assigned_since = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vehicles'
        # license_plate unique per provider
        unique_together = [('provider', 'license_plate')]

    def __str__(self):
        return f'{self.brand} {self.model_number} ({self.license_plate})'


# Insurance record — OneToOne with Vehicle, created atomically
class VehicleInsurance(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.OneToOneField(Vehicle, on_delete=models.CASCADE, related_name='insurance')
    insurance_provider = models.CharField(max_length=255, blank=True)
    policy_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    monthly_premium = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    liability_coverage = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    collision_coverage = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    comprehensive_coverage = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'vehicle_insurance'

    def __str__(self):
        return f'Insurance for {self.vehicle}'


# Maintenance records — multiple per vehicle
class VehicleMaintenance(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='maintenance_records')
    maintenance_type = models.CharField(max_length=255)
    scheduled_date = models.DateField(null=True, blank=True)
    completed_date = models.DateField(null=True, blank=True)
    mileage_at_service = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    next_service_date = models.DateField(null=True, blank=True)
    next_service_mileage = models.PositiveIntegerField(default=0)

    # Snapshot values at time of record
    current_mileage = models.PositiveIntegerField(default=0)
    last_service = models.DateField(null=True, blank=True)
    upcoming_service = models.CharField(max_length=255, blank=True)

    # Maintenance interval tracking
    service_interval = models.PositiveIntegerField(default=0)  # miles between services
    last_service_mileage = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vehicle_maintenance'
        ordering = ['-scheduled_date']

    def __str__(self):
        return f'{self.maintenance_type} — {self.vehicle}'


# Documents attached to a vehicle
class VehicleDocument(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='documents')
    document_name = models.CharField(max_length=255)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='vehicles/documents/')
    uploaded_date = models.DateField(auto_now_add=True)
    expires_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vehicle_documents'
        ordering = ['-uploaded_date']

    def __str__(self):
        return f'{self.document_name} — {self.vehicle}'