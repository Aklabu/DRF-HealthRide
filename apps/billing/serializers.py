import re
from rest_framework import serializers
from .models import (
    StripeAccount, BankAccount, Invoice, InvoiceItem,
    InvoiceTemplate, LateFeeConfig,
)


# Stripe connection status serializer
class StripeStatusSerializer(serializers.ModelSerializer):

    connected = serializers.BooleanField(source='is_connected')

    class Meta:
        model = StripeAccount
        fields = [
            'connected', 'stripe_account_id',
            'onboarding_completed', 'charges_enabled', 'payouts_enabled',
        ]


# Bank account — never exposes account_number_encrypted
class BankAccountSerializer(serializers.ModelSerializer):

    class Meta:
        model = BankAccount
        fields = ['bank_name', 'routing_number', 'account_number', 'verified']
        read_only_fields = ['routing_number', 'account_number', 'verified']


# Bank account creation/update — accepts raw numbers, masks before save
class BankAccountWriteSerializer(serializers.Serializer):

    bank_name = serializers.CharField(max_length=255)
    routing_number = serializers.CharField(max_length=9)
    account_number = serializers.CharField(max_length=17)

    def validate_routing_number(self, value):
        if not re.fullmatch(r'\d{9}', value):
            raise serializers.ValidationError('Routing number must be exactly 9 digits.')
        return value

    def validate_account_number(self, value):
        if not re.fullmatch(r'\d{4,17}', value):
            raise serializers.ValidationError('Account number must be between 4 and 17 digits.')
        return value


# Invoice list row
class InvoiceListSerializer(serializers.ModelSerializer):

    facility_name = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'facility_name',
            'period_start', 'period_end',
            'issue_date', 'due_date', 'paid_date',
            'trips_count', 'subtotal', 'late_fee_amount',
            'amount', 'status',
        ]

    def get_facility_name(self, obj):
        if obj.facility:
            return obj.facility.facility_name
        return None


# Invoice line item
class InvoiceItemSerializer(serializers.ModelSerializer):

    class Meta:
        model = InvoiceItem
        fields = [
            'trip_date', 'passenger_name',
            'pickup_address', 'dropoff_address',
            'trip_type', 'amount',
        ]


# Full invoice detail with line items
class InvoiceDetailSerializer(serializers.ModelSerializer):

    facility = serializers.SerializerMethodField()
    items = InvoiceItemSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'facility',
            'period_start', 'period_end',
            'issue_date', 'due_date', 'paid_date',
            'status', 'notes',
            'subtotal', 'late_fee_amount', 'amount',
            'trips_count', 'items',
        ]

    def get_facility(self, obj):
        if obj.facility:
            return {
                'facility_name': obj.facility.facility_name,
                'facility_id': obj.facility.facility_id,
            }
        return None


# Invoice creation request
class InvoiceCreateSerializer(serializers.Serializer):

    facility_id = serializers.UUIDField(required=False, allow_null=True)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        if attrs['period_start'] >= attrs['period_end']:
            raise serializers.ValidationError(
                {'period_end': 'period_end must be after period_start.'}
            )
        return attrs


# Invoice status update
class InvoiceStatusUpdateSerializer(serializers.Serializer):

    status = serializers.ChoiceField(choices=['sent', 'paid'])


# Invoice template
class InvoiceTemplateSerializer(serializers.ModelSerializer):

    class Meta:
        model = InvoiceTemplate
        fields = ['invoice_number_prefix', 'payment_terms', 'footer_text']

    def validate_invoice_number_prefix(self, value):
        if not re.fullmatch(r'[A-Za-z0-9]{1,10}', value):
            raise serializers.ValidationError(
                'Prefix must be alphanumeric, max 10 characters, no spaces.'
            )
        return value.upper()

    def validate_payment_terms(self, value):
        if value <= 0:
            raise serializers.ValidationError('payment_terms must be a positive integer.')
        return value


# Late fee config
class LateFeeConfigSerializer(serializers.ModelSerializer):

    class Meta:
        model = LateFeeConfig
        fields = ['late_fee_percentage', 'grace_period_days']

    def validate_late_fee_percentage(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError(
                'late_fee_percentage must be between 0 and 100.'
            )
        return value

    def validate_grace_period_days(self, value):
        if value < 0:
            raise serializers.ValidationError(
                'grace_period_days must be a non-negative integer.'
            )
        return value
