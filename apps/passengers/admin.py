from django.contrib import admin
from .models import (
    Passenger, PassengerMedical, PassengerEmergencyContact,
    PassengerInsurance, PassengerCommonLocation, PassengerFacility, PreferredDriver,
)


# Passenger admin
@admin.register(Passenger)
class PassengerAdmin(admin.ModelAdmin):
    list_display = [
        'full_name', 'email', 'phone_number',
        'mobility', 'status', 'provider', 'created_at'
    ]
    list_filter = ['mobility', 'status']
    search_fields = ['first_name', 'last_name', 'email', 'phone_number']
    readonly_fields = [
        'id', 'total_trips', 'completed_trips',
        'total_spent', 'outstanding_balance', 'created_at', 'updated_at'
    ]
    ordering = ['-created_at']


# Medical info
@admin.register(PassengerMedical)
class PassengerMedicalAdmin(admin.ModelAdmin):
    list_display = ['passenger', 'special_requirements']
    list_filter = ['special_requirements']
    search_fields = ['passenger__first_name', 'passenger__last_name']
    readonly_fields = ['id']


# Emergency contact
@admin.register(PassengerEmergencyContact)
class PassengerEmergencyContactAdmin(admin.ModelAdmin):
    list_display = ['passenger', 'full_name', 'phone_number', 'relation']
    search_fields = ['passenger__first_name', 'full_name']
    readonly_fields = ['id']


# Insurance
@admin.register(PassengerInsurance)
class PassengerInsuranceAdmin(admin.ModelAdmin):
    list_display = ['passenger', 'insurance_provider', 'policy_number', 'expiry_date']
    search_fields = ['passenger__first_name', 'policy_number']
    readonly_fields = ['id']


# Common locations
@admin.register(PassengerCommonLocation)
class PassengerCommonLocationAdmin(admin.ModelAdmin):
    list_display = ['passenger', 'location_name', 'trips_count', 'created_at']
    search_fields = ['passenger__first_name', 'location_name']
    readonly_fields = ['id', 'trips_count', 'created_at']


# Facility associations
@admin.register(PassengerFacility)
class PassengerFacilityAdmin(admin.ModelAdmin):
    list_display = ['passenger', 'facility', 'created_at']
    search_fields = ['passenger__first_name', 'facility__facility_name']
    readonly_fields = ['id', 'created_at']


# Preferred drivers — read-only, managed by trips app
@admin.register(PreferredDriver)
class PreferredDriverAdmin(admin.ModelAdmin):
    list_display = ['passenger', 'driver', 'trips_count', 'created_at']
    search_fields = ['passenger__first_name', 'driver__full_name']
    readonly_fields = ['id', 'trips_count', 'created_at']