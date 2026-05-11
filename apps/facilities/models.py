import uuid
from django.db import models
from apps.accounts.models import Provider


# Facility type choices
FACILITY_TYPE_CHOICES = [
    ('hospital', 'Hospital'),
    ('clinic', 'Clinic'),
    ('nursing_home', 'Nursing Home'),
    ('dialysis_center', 'Dialysis Center'),
    ('rehabilitation', 'Rehabilitation'),
    ('other', 'Other'),
]

# Facility status choices
FACILITY_STATUS_CHOICES = [
    ('active', 'Active'),
    ('inactive', 'Inactive'),
]

# Billing cycle choices
BILLING_CYCLE_CHOICES = [
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
]

# Contract status choices
CONTRACT_STATUS_CHOICES = [
    ('active', 'Active'),
    ('inactive', 'Inactive'),
    ('expired', 'Expired'),
]

# Document type choices
DOCUMENT_TYPE_CHOICES = [
    ('w9_tax_form', 'W9 Tax Form'),
    ('hipaa_agreement', 'HIPAA Agreement'),
    ('insurance_certificate', 'Insurance Certificate'),
    ('contract', 'Contract'),
    ('other', 'Other'),
]


# Core facility model
class Facility(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='facilities')

    # Basic info
    facility_name = models.CharField(max_length=255)
    facility_type = models.CharField(max_length=30, choices=FACILITY_TYPE_CHOICES)

    # Auto-generated public-facing ID — FAC-XXXXXX, non-editable after creation
    facility_id = models.CharField(max_length=20, unique=True, editable=False)

    # Location
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    pickup_instructions = models.TextField(blank=True, null=True)

    # Status
    status = models.CharField(max_length=10, choices=FACILITY_STATUS_CHOICES, default='active')

    # Denormalized stats — updated by trips and billing apps
    total_trips = models.PositiveIntegerField(default=0)
    total_trips_this_month = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_revenue_this_month = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    outstanding_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    outstanding_last_date = models.DateField(null=True, blank=True)
    avg_payment_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'facilities'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.facility_name} ({self.facility_id})'

    def save(self, *args, **kwargs):
        # Auto-generate facility_id on first save
        if not self.facility_id:
            self.facility_id = self._generate_facility_id()
        super().save(*args, **kwargs)

    def _generate_facility_id(self):
        # Query globally — facility_id is unique across all providers
        # Use a retry loop to handle concurrent inserts safely
        import random
        for _ in range(10):
            existing = Facility.objects.filter(
                facility_id__startswith='FAC-'
            ).order_by('-facility_id').values_list('facility_id', flat=True).first()

            if existing:
                try:
                    last_num = int(existing.replace('FAC-', ''))
                except ValueError:
                    last_num = 0
            else:
                last_num = 0

            candidate = f'FAC-{str(last_num + 1).zfill(6)}'

            # Check candidate is not already taken before returning
            if not Facility.objects.filter(facility_id=candidate).exists():
                return candidate

        # Fallback — use random suffix to avoid collision
        return f'FAC-{str(uuid.uuid4().int)[:6].zfill(6)}'


# Primary contact — OneToOne per facility
class FacilityPrimaryContact(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.OneToOneField(Facility, on_delete=models.CASCADE, related_name='primary_contact')
    full_name = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        db_table = 'facility_primary_contacts'

    def __str__(self):
        return f'Primary contact for {self.facility}'


# Billing contact — OneToOne per facility
class FacilityBillingContact(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.OneToOneField(Facility, on_delete=models.CASCADE, related_name='billing_contact')
    full_name = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    insurance_no = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'facility_billing_contacts'

    def __str__(self):
        return f'Billing contact for {self.facility}'


# Contract — OneToOne per facility
class FacilityContract(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.OneToOneField(Facility, on_delete=models.CASCADE, related_name='contract')
    contract_number = models.CharField(max_length=100, unique=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLE_CHOICES, default='monthly')
    payment_terms = models.CharField(max_length=50, blank=True)
    volume_commitment = models.PositiveIntegerField(default=0)
    auto_renewal = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=CONTRACT_STATUS_CHOICES, default='active')

    class Meta:
        db_table = 'facility_contracts'

    def __str__(self):
        return f'Contract {self.contract_number} for {self.facility}'


# Pricing — OneToOne per facility
class FacilityPricing(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.OneToOneField(Facility, on_delete=models.CASCADE, related_name='pricing')
    standard_sedan_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    wheelchair_accessible_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    stretcher_transport_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    wait_time_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    minimum_trips = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'facility_pricing'

    def __str__(self):
        return f'Pricing for {self.facility}'


# Tax info — OneToOne per facility
class FacilityTax(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.OneToOneField(Facility, on_delete=models.CASCADE, related_name='tax')
    tax_id = models.CharField(max_length=100, blank=True)
    tax_exempt = models.BooleanField(default=False)
    w9_on_file = models.BooleanField(default=False)

    class Meta:
        db_table = 'facility_tax'

    def __str__(self):
        return f'Tax info for {self.facility}'


# Documents — FK, multiple per facility
class FacilityDocument(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='documents')
    document_name = models.CharField(max_length=255)
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='facilities/documents/')
    uploaded_date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'facility_documents'
        ordering = ['-uploaded_date']

    def __str__(self):
        return f'{self.document_name} — {self.facility}'