from django.contrib import admin
from .models import (
    PreTripInspection, ComplianceDocument, ComplianceAlert, InspectionSchedule,
)


@admin.register(PreTripInspection)
class PreTripInspectionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'driver', 'vehicle', 'date_time',
        'status', 'fuel_level', 'odometer',
    ]
    list_filter = ['status', 'fuel_level']
    search_fields = ['driver__full_name', 'vehicle__license_plate']
    readonly_fields = ['id', 'created_at']
    ordering = ['-date_time']


@admin.register(ComplianceDocument)
class ComplianceDocumentAdmin(admin.ModelAdmin):
    list_display = [
        'holder_name', 'holder_type', 'document_type',
        'expiration_date', 'days_until_expiration', 'status', 'is_active',
    ]
    list_filter = ['status', 'holder_type', 'document_type', 'is_active']
    search_fields = ['holder_name', 'document_number']
    readonly_fields = ['id', 'last_checked_at', 'created_at', 'updated_at']
    ordering = ['days_until_expiration']


@admin.register(ComplianceAlert)
class ComplianceAlertAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'severity', 'alert_type',
        'holder_name', 'days_remaining', 'is_resolved', 'created_at',
    ]
    list_filter = ['severity', 'alert_type', 'is_resolved']
    search_fields = ['title', 'holder_name']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']


@admin.register(InspectionSchedule)
class InspectionScheduleAdmin(admin.ModelAdmin):
    list_display = [
        'driver', 'vehicle', 'expected_date',
        'inspection_submitted', 'missed_alert_sent',
    ]
    list_filter = ['inspection_submitted', 'missed_alert_sent']
    search_fields = ['driver__full_name', 'vehicle__license_plate']
    readonly_fields = ['id', 'created_at']
    ordering = ['-expected_date']
