from django.contrib import admin
from .models import Vehicle, VehicleInsurance, VehicleMaintenance, VehicleDocument


# Vehicle admin — provider-scoped display
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = [
        'license_plate', 'brand', 'model_number', 'year',
        'vehicle_type', 'status', 'provider', 'assigned_driver', 'created_at'
    ]
    list_filter = ['vehicle_type', 'status', 'accessibility_features']
    search_fields = ['license_plate', 'vin_number', 'brand', 'model_number']
    readonly_fields = ['id', 'last_inspection', 'next_due', 'inspector', 'created_at', 'updated_at']
    ordering = ['-created_at']


# Insurance records
@admin.register(VehicleInsurance)
class VehicleInsuranceAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'insurance_provider', 'policy_number', 'expiry_date']
    search_fields = ['vehicle__license_plate', 'policy_number']
    readonly_fields = ['id']


# Maintenance records
@admin.register(VehicleMaintenance)
class VehicleMaintenanceAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'maintenance_type', 'scheduled_date', 'completed_date', 'current_mileage']
    list_filter = ['maintenance_type']
    search_fields = ['vehicle__license_plate']
    readonly_fields = ['id', 'created_at']
    ordering = ['-scheduled_date']


# Documents
@admin.register(VehicleDocument)
class VehicleDocumentAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'document_name', 'document_type', 'uploaded_date', 'expires_date']
    list_filter = ['document_type']
    search_fields = ['vehicle__license_plate', 'document_name']
    readonly_fields = ['id', 'uploaded_date', 'created_at']