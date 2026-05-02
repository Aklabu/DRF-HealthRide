from django.contrib import admin
from .models import (
    Driver, DriverLicense, DriverEmergencyContact,
    DriverCertification, DriverDocument, DriverAvailability,
    DriverWorkLog, DriverPayout,
)


# Driver admin
@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = [
        'full_name', 'email', 'phone_number',
        'status_employment', 'status_availability',
        'provider', 'joined_date'
    ]
    list_filter = ['status_employment', 'status_availability']
    search_fields = ['full_name', 'email', 'phone_number']
    readonly_fields = ['id', 'joined_date', 'total_trips', 'on_time_rate', 'created_at', 'updated_at']
    ordering = ['-created_at']


# Driver license
@admin.register(DriverLicense)
class DriverLicenseAdmin(admin.ModelAdmin):
    list_display = ['driver', 'license_number', 'license_state', 'license_expiry_date']
    search_fields = ['driver__full_name', 'license_number']
    readonly_fields = ['id']


# Emergency contact
@admin.register(DriverEmergencyContact)
class DriverEmergencyContactAdmin(admin.ModelAdmin):
    list_display = ['driver', 'name', 'phone', 'relationship']
    search_fields = ['driver__full_name', 'name']
    readonly_fields = ['id']


# Certifications
@admin.register(DriverCertification)
class DriverCertificationAdmin(admin.ModelAdmin):
    list_display = ['driver', 'cert_type', 'is_active', 'expiry_date', 'updated_at']
    list_filter = ['cert_type', 'is_active']
    search_fields = ['driver__full_name']
    readonly_fields = ['id']


# Documents
@admin.register(DriverDocument)
class DriverDocumentAdmin(admin.ModelAdmin):
    list_display = ['driver', 'document_type', 'upload_date', 'expire_date']
    list_filter = ['document_type']
    search_fields = ['driver__full_name']
    readonly_fields = ['id', 'upload_date', 'created_at']


# Availability
@admin.register(DriverAvailability)
class DriverAvailabilityAdmin(admin.ModelAdmin):
    list_display = ['driver', 'day_of_week', 'is_available', 'start_time', 'end_time']
    list_filter = ['is_available', 'day_of_week']
    search_fields = ['driver__full_name']
    readonly_fields = ['id']


# Work logs — read-only, managed by trips app
@admin.register(DriverWorkLog)
class DriverWorkLogAdmin(admin.ModelAdmin):
    list_display = ['driver', 'date', 'hours_worked', 'trips_completed', 'earnings', 'status']
    list_filter = ['status']
    search_fields = ['driver__full_name']
    readonly_fields = ['id', 'created_at', 'earnings']
    ordering = ['-date']


# Payouts
@admin.register(DriverPayout)
class DriverPayoutAdmin(admin.ModelAdmin):
    list_display = ['driver', 'from_date', 'to_date', 'total_hours', 'total_amount', 'created_at']
    search_fields = ['driver__full_name']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']