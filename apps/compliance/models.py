import uuid
from django.db import models
from apps.accounts.models import Provider
from apps.drivers.models import Driver
from apps.vehicles.models import Vehicle


# Constants defining choice fields used by compliance models
FUEL_LEVEL_CHOICES = [
    ('full', 'Full'),
    ('three_quarters', 'Three Quarters'),
    ('half', 'Half'),
    ('quarter', 'Quarter'),
    ('low', 'Low'),
]

INSPECTION_STATUS_CHOICES = [
    ('all_clear', 'All Clear'),
    ('issues_found', 'Issues Found'),
]

CHECKLIST_CHOICES = [
    ('pass', 'Pass'),
    ('fail', 'Fail'),
]

WHEELCHAIR_RAMP_CHOICES = [
    ('pass', 'Pass'),
    ('fail', 'Fail'),
    ('not_applicable', 'Not Applicable'),
]

HOLDER_TYPE_CHOICES = [
    ('driver', 'Driver'),
    ('vehicle', 'Vehicle'),
]

DOCUMENT_TYPE_CHOICES = [
    ('driver_license', 'Driver License'),
    ('insurance', 'Insurance'),
    ('cpr_certificate', 'CPR Certificate'),
    ('background_check', 'Background Check'),
    ('vehicle_registration', 'Vehicle Registration'),
    ('vehicle_insurance', 'Vehicle Insurance'),
    ('w9', 'W9'),
    ('hipaa_agreement', 'HIPAA Agreement'),
    ('others', 'Others'),
]

DOCUMENT_STATUS_CHOICES = [
    ('valid', 'Valid'),
    ('expiring_soon', 'Expiring Soon'),
    ('expired', 'Expired'),
]

ALERT_TYPE_CHOICES = [
    ('document_expiring', 'Document Expiring'),
    ('document_expired', 'Document Expired'),
    ('inspection_missed', 'Inspection Missed'),
    ('inspection_failed', 'Inspection Failed'),
]

SEVERITY_CHOICES = [
    ('critical', 'Critical'),
    ('warning', 'Warning'),
    ('info', 'Info'),
]


# Model definitions for compliance tracking
class PreTripInspection(models.Model):
    """Daily vehicle checklist submitted by a driver before starting trips."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='inspections')
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='inspections'
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='inspections'
    )

    date_time = models.DateTimeField()
    odometer = models.PositiveIntegerField()
    fuel_level = models.CharField(max_length=20, choices=FUEL_LEVEL_CHOICES)

    # Status derived automatically from checklist results
    status = models.CharField(
        max_length=15, choices=INSPECTION_STATUS_CHOICES, default='all_clear'
    )

    # Pre-trip inspection checklist fields
    vehicle_exterior = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    vehicle_interior = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    tires = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    brakes = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    fluids = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    lights = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    safety_equipment = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    cleanliness = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)
    wheelchair_ramp = models.CharField(
        max_length=15, choices=WHEELCHAIR_RAMP_CHOICES, default='not_applicable'
    )
    dashboard_warning_lights = models.CharField(max_length=5, choices=CHECKLIST_CHOICES)

    # Issue details; required when any checklist item failed
    issue_description = models.TextField(null=True, blank=True)
    issue_photo = models.FileField(upload_to='compliance/inspections/', null=True, blank=True)

    # Captured driver signature file from the driver app
    signature = models.FileField(upload_to='compliance/signatures/')

    created_at = models.DateTimeField(auto_now_add=True)

    # Checklist fields considered safety-critical for alert escalation
    SAFETY_CRITICAL_FIELDS = ['brakes', 'lights', 'tires', 'safety_equipment']

    class Meta:
        db_table = 'pre_trip_inspections'
        ordering = ['-date_time']

    def __str__(self):
        driver_name = self.driver.full_name if self.driver else 'Unknown'
        return f'Inspection by {driver_name} on {self.date_time.date()}'

    def has_critical_failure(self):
        """Return True if any safety-critical checklist item failed."""
        return any(
            getattr(self, field) == 'fail'
            for field in self.SAFETY_CRITICAL_FIELDS
        )


# ComplianceDocument and ComplianceAlert models serve as the core of our compliance tracking system.
class ComplianceDocument(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='compliance_documents'
    )

    holder_type = models.CharField(max_length=10, choices=HOLDER_TYPE_CHOICES)
    holder_id = models.UUIDField()
    holder_name = models.CharField(max_length=255)  # denormalized for display

    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    document_number = models.CharField(max_length=100, blank=True, null=True)

    # Reference to the compliance file location stored in another app
    file_reference = models.URLField(max_length=500, blank=True)

    upload_date = models.DateField()
    expiration_date = models.DateField(null=True, blank=True)

    # Fields calculated by periodic background task
    status = models.CharField(
        max_length=15, choices=DOCUMENT_STATUS_CHOICES, default='valid'
    )
    days_until_expiration = models.IntegerField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    # Suppresses duplicate notifications within 7 days
    notified_at = models.DateTimeField(null=True, blank=True)

    # Soft delete flag to preserve audit history
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'compliance_documents'
        ordering = ['days_until_expiration']

    def __str__(self):
        return f'{self.document_type} — {self.holder_name}'


# ComplianceAlert records are created when a compliance issue is detected, such as an expiring document or a failed inspection.
class ComplianceAlert(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='compliance_alerts'
    )

    alert_type = models.CharField(max_length=25, choices=ALERT_TYPE_CHOICES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)

    title = models.CharField(max_length=255)
    description = models.TextField()

    holder_type = models.CharField(max_length=10, choices=HOLDER_TYPE_CHOICES)
    holder_id = models.UUIDField()
    holder_name = models.CharField(max_length=255)  # denormalized

    related_document = models.ForeignKey(
        ComplianceDocument, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='alerts'
    )
    related_inspection = models.ForeignKey(
        PreTripInspection, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='alerts'
    )

    days_remaining = models.IntegerField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'compliance_alerts'
        ordering = [
            models.Case(
                models.When(severity='critical', then=0),
                models.When(severity='warning', then=1),
                models.When(severity='info', then=2),
                default=3,
                output_field=models.IntegerField(),
            ),
            'days_remaining',
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.title}'


# InspectionSchedule is used to track expected pre-trip inspections for driver-vehicle pairs on specific dates
class InspectionSchedule(models.Model):
    """
    Tracks which driver-vehicle pairs are expected to submit a pre-trip
    inspection on a given date. Enables missed inspection detection.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='inspection_schedules'
    )
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='inspection_schedules')
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='inspection_schedules')

    expected_date = models.DateField()

    # Marked true once the expected inspection is submitted
    inspection_submitted = models.BooleanField(default=False)

    # Reference to the submitted inspection
    inspection = models.ForeignKey(
        PreTripInspection, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='schedule'
    )

    # Prevents duplicate missed-inspection alerts
    missed_alert_sent = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inspection_schedules'
        unique_together = [('provider', 'driver', 'vehicle', 'expected_date')]
        ordering = ['-expected_date']

    def __str__(self):
        return (
            f'Schedule: {self.driver.full_name} / '
            f'{self.vehicle.license_plate} on {self.expected_date}'
        )
