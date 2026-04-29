from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Provider, OTPVerification, ProviderSettings, RateCard, SuperAdmin


# Provider admin - custom display for business-focused fields
@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ['business_email', 'business_name', 'is_active', 'is_verified', 'created_at']
    list_filter = ['is_active', 'is_verified']
    search_fields = ['business_email', 'business_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']


# OTP records — read-only audit view
@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ['email', 'purpose', 'is_used', 'created_at', 'expires_at']
    list_filter = ['purpose', 'is_used']
    search_fields = ['email']
    readonly_fields = ['id', 'otp_code', 'created_at', 'expires_at']
    ordering = ['-created_at']


# Provider settings
@admin.register(ProviderSettings)
class ProviderSettingsAdmin(admin.ModelAdmin):
    list_display = ['provider', 'enable_auto_assignment', 'cancellation_window']
    search_fields = ['provider__business_email']
    readonly_fields = ['id']


# Rate card
@admin.register(RateCard)
class RateCardAdmin(admin.ModelAdmin):
    list_display = ['provider', 'standard_base_fare', 'wheelchair_base_fare', 'stretcher_base_fare']
    search_fields = ['provider__business_email']
    readonly_fields = ['id']


# Super admin
@admin.register(SuperAdmin)
class SuperAdminAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_staff', 'is_superuser', 'created_at']
    readonly_fields = ['id', 'created_at']