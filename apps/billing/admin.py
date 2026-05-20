from django.contrib import admin
from .models import (
    StripeAccount, BankAccount, Invoice, InvoiceItem,
    InvoiceTemplate, LateFeeConfig,
)


@admin.register(StripeAccount)
class StripeAccountAdmin(admin.ModelAdmin):
    list_display = [
        'provider', 'stripe_account_id', 'is_connected',
        'onboarding_completed', 'charges_enabled', 'payouts_enabled',
    ]
    readonly_fields = ['id', 'created_at', 'updated_at']
    search_fields = ['provider__business_email', 'stripe_account_id']


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['provider', 'bank_name', 'routing_number', 'account_number', 'verified']
    readonly_fields = ['id', 'account_number_encrypted', 'created_at', 'updated_at']
    search_fields = ['provider__business_email', 'bank_name']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'invoice_number', 'provider', 'facility',
        'issue_date', 'due_date', 'paid_date',
        'trips_count', 'amount', 'status',
    ]
    list_filter = ['status']
    search_fields = ['invoice_number', 'provider__business_email']
    readonly_fields = ['id', 'invoice_number', 'created_at', 'updated_at']
    ordering = ['-issue_date']


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = [
        'invoice', 'trip', 'trip_date',
        'passenger_name', 'trip_type', 'amount',
    ]
    search_fields = ['invoice__invoice_number', 'passenger_name']
    readonly_fields = ['id']


@admin.register(InvoiceTemplate)
class InvoiceTemplateAdmin(admin.ModelAdmin):
    list_display = ['provider', 'invoice_number_prefix', 'payment_terms']
    readonly_fields = ['id', 'created_at', 'updated_at']
    search_fields = ['provider__business_email']


@admin.register(LateFeeConfig)
class LateFeeConfigAdmin(admin.ModelAdmin):
    list_display = ['provider', 'late_fee_percentage', 'grace_period_days']
    readonly_fields = ['id', 'created_at', 'updated_at']
    search_fields = ['provider__business_email']
