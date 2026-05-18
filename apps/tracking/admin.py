from django.contrib import admin
from .models import DriverLocation, DriverLocationHistory, ActiveTripTracking


# Current driver positions — live state
@admin.register(DriverLocation)
class DriverLocationAdmin(admin.ModelAdmin):
    list_display = [
        'driver', 'provider', 'latitude', 'longitude',
        'is_online', 'heading', 'speed', 'timestamp',
    ]
    list_filter = ['is_online']
    search_fields = ['driver__full_name', 'provider__business_email']
    readonly_fields = ['id', 'timestamp']


# Location history — audit trail
@admin.register(DriverLocationHistory)
class DriverLocationHistoryAdmin(admin.ModelAdmin):
    list_display = ['driver', 'latitude', 'longitude', 'trip', 'timestamp']
    list_filter = ['driver']
    search_fields = ['driver__full_name']
    readonly_fields = ['id', 'timestamp']
    ordering = ['-timestamp']


# Active trip tracking — live trip state
@admin.register(ActiveTripTracking)
class ActiveTripTrackingAdmin(admin.ModelAdmin):
    list_display = [
        'trip', 'driver', 'provider',
        'current_lat', 'current_lng',
        'eta_minutes', 'status', 'last_updated',
    ]
    list_filter = ['status']
    search_fields = ['trip__trip_number', 'driver__full_name']
    readonly_fields = ['id', 'last_updated']
