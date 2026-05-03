from django.contrib import admin
from .models import (
    Facility, FacilityPrimaryContact, FacilityBillingContact,
    FacilityContract, FacilityPricing, FacilityTax, FacilityDocument,
)


# Facility admin
@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = [
        'facility_name', 'facility_id', 'facility_type',
        'status', 'provider', 'total_trips', 'outstanding_amount', 'created_at'
    ]
    list_filter = ['facility_type', 'status']
    search_fields = ['facility_name', 'facility_id']
    readonly_fields = [
        'id', 'facility_id', 'total_trips', 'total_trips_this_month',
        'total_revenue', 'total_revenue_this_month',
        'outstanding_amount', 'avg_payment_days', 'created_at', 'updated_at'
    ]
    ordering = ['-created_at']


# Primary contact
@admin.register(FacilityPrimaryContact)
class FacilityPrimaryContactAdmin(admin.ModelAdmin):
    list_display = ['facility', 'full_name', 'title', 'phone', 'email']
    search_fields = ['facility__facility_name', 'full_name']
    readonly_fields = ['id']


# Billing contact
@admin.register(FacilityBillingContact)
class FacilityBillingContactAdmin(admin.ModelAdmin):
    list_display = ['facility', 'full_name', 'title', 'phone', 'email']
    search_fields = ['facility__facility_name', 'full_name']
    readonly_fields = ['id']


# Contract
@admin.register(FacilityContract)
class FacilityContractAdmin(admin.ModelAdmin):
    list_display = [
        'facility', 'contract_number', 'status',
        'start_date', 'end_date', 'billing_cycle', 'auto_renewal'
    ]
    list_filter = ['status', 'billing_cycle', 'auto_renewal']
    search_fields = ['facility__facility_name', 'contract_number']
    readonly_fields = ['id']


# Pricing
@admin.register(FacilityPricing)
class FacilityPricingAdmin(admin.ModelAdmin):
    list_display = [
        'facility', 'standard_sedan_rate',
        'wheelchair_accessible_rate', 'stretcher_transport_rate',
        'discount_percentage'
    ]
    search_fields = ['facility__facility_name']
    readonly_fields = ['id']


# Tax
@admin.register(FacilityTax)
class FacilityTaxAdmin(admin.ModelAdmin):
    list_display = ['facility', 'tax_id', 'tax_exempt', 'w9_on_file']
    list_filter = ['tax_exempt', 'w9_on_file']
    search_fields = ['facility__facility_name', 'tax_id']
    readonly_fields = ['id']


# Documents
@admin.register(FacilityDocument)
class FacilityDocumentAdmin(admin.ModelAdmin):
    list_display = ['facility', 'document_name', 'document_type', 'uploaded_date']
    list_filter = ['document_type']
    search_fields = ['facility__facility_name', 'document_name']
    readonly_fields = ['id', 'uploaded_date', 'created_at']