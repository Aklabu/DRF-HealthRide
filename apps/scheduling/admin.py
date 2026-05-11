from django.contrib import admin
from .models import DailySchedule, ScheduleSlot, AIAssignmentLog


# Daily schedule — one per provider per date
@admin.register(DailySchedule)
class DailyScheduleAdmin(admin.ModelAdmin):
    list_display = [
        'date', 'provider', 'total_trips', 'completed_trips',
        'in_progress', 'scheduled', 'unassigned',
    ]
    list_filter = ['date']
    search_fields = ['provider__business_email']
    readonly_fields = [
        'id', 'total_trips', 'completed_trips',
        'in_progress', 'scheduled', 'unassigned',
        'created_at', 'updated_at',
    ]
    ordering = ['-date']


# Schedule slots — one per trip per daily schedule
@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = [
        'trip', 'schedule', 'driver',
        'assignment_method', 'assigned_at',
    ]
    list_filter = ['assignment_method']
    search_fields = ['trip__trip_number', 'driver__full_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['schedule__date', 'trip__pickup_time']


# AI assignment logs — full audit trail
@admin.register(AIAssignmentLog)
class AIAssignmentLogAdmin(admin.ModelAdmin):
    list_display = [
        'trip', 'provider', 'selected_driver',
        'assignment_successful', 'created_at',
    ]
    list_filter = ['assignment_successful']
    search_fields = ['trip__trip_number', 'provider__business_email']
    readonly_fields = ['id', 'drivers_considered', 'created_at']
    ordering = ['-created_at']
