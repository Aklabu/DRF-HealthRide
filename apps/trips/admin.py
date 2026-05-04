from django.contrib import admin
from .models import (
    Trip, RecurringTripConfig, TripPassengerContact,
    TripSignature, TripStatusLog,
)


# Trip admin
@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = [
        'trip_number', 'trip_type', 'status', 'payment_status',
        'passenger', 'driver', 'pickup_date', 'pickup_time',
        'total_amount', 'provider', 'created_at',
    ]
    list_filter = ['status', 'payment_status', 'trip_type', 'special_requirements']
    search_fields = ['trip_number', 'pickup_address', 'dropoff_address']
    readonly_fields = [
        'id', 'trip_number', 'assigned_at', 'started_at',
        'completed_at', 'cancelled_at', 'created_at', 'updated_at',
    ]
    ordering = ['pickup_date', 'pickup_time']


# Recurring config
@admin.register(RecurringTripConfig)
class RecurringTripConfigAdmin(admin.ModelAdmin):
    list_display = ['trip', 'frequency', 'end_date', 'last_generated_date']
    readonly_fields = ['id']


# Passenger contact
@admin.register(TripPassengerContact)
class TripPassengerContactAdmin(admin.ModelAdmin):
    list_display = ['trip', 'full_name', 'phone_number', 'relation']
    search_fields = ['full_name', 'trip__trip_number']
    readonly_fields = ['id']


# Signature — read-only audit
@admin.register(TripSignature)
class TripSignatureAdmin(admin.ModelAdmin):
    list_display = ['trip', 'signed_at', 'confirmed_by_driver']
    readonly_fields = ['id', 'signed_at']


# Status log — fully read-only
@admin.register(TripStatusLog)
class TripStatusLogAdmin(admin.ModelAdmin):
    list_display = ['trip', 'from_status', 'to_status', 'changed_by', 'changed_at']
    list_filter = ['changed_by', 'to_status']
    search_fields = ['trip__trip_number']
    readonly_fields = ['id', 'changed_at']
    ordering = ['-changed_at']