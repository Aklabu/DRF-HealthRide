from rest_framework import serializers
from django.utils import timezone
from .models import (
    Facility, FacilityPrimaryContact, FacilityBillingContact,
    FacilityContract, FacilityPricing, FacilityTax, FacilityDocument,
)


# Facility list row serializer
class FacilityListSerializer(serializers.ModelSerializer):

    address = serializers.SerializerMethodField()
    primary_contact_name = serializers.SerializerMethodField()
    primary_contact_number = serializers.SerializerMethodField()
    contract_from = serializers.SerializerMethodField()
    contract_to = serializers.SerializerMethodField()
    performance = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()

    class Meta:
        model = Facility
        fields = [
            'id', 'facility_name', 'facility_id', 'address',
            'primary_contact_name', 'primary_contact_number',
            'contract_from', 'contract_to',
            'performance', 'outstanding', 'status',
        ]

    def get_address(self, obj):
        parts = [obj.street_address, obj.city, obj.state, obj.zip_code]
        return ', '.join(p for p in parts if p)

    def get_primary_contact_name(self, obj):
        try:
            return obj.primary_contact.full_name
        except Exception:
            return None

    def get_primary_contact_number(self, obj):
        try:
            return obj.primary_contact.phone
        except Exception:
            return None

    def get_contract_from(self, obj):
        try:
            return obj.contract.start_date
        except Exception:
            return None

    def get_contract_to(self, obj):
        try:
            return obj.contract.end_date
        except Exception:
            return None

    def get_performance(self, obj):
        # Build last 6 months trip and revenue arrays
        today = timezone.now().date()
        trips_by_month = []
        amounts_by_month = []

        for i in range(5, -1, -1):
            # Get first day of each of last 6 months
            month = (today.month - i - 1) % 12 + 1
            year = today.year - ((today.month - i - 1) // 12)
            trips_by_month.append({'month': f'{year}-{str(month).zfill(2)}', 'trips': 0})
            amounts_by_month.append({'month': f'{year}-{str(month).zfill(2)}', 'amount': '0.00'})

        return {
            'trips_by_month': trips_by_month,
            'amounts_by_month': amounts_by_month,
            'total_amount': str(obj.total_revenue),
        }

    def get_outstanding(self, obj):
        return {
            'amount': str(obj.outstanding_amount),
            'last_date': obj.outstanding_last_date,
        }


# Facility creation serializer
class FacilityCreateSerializer(serializers.Serializer):

    # Basic info
    facility_name = serializers.CharField(max_length=255)
    facility_type = serializers.ChoiceField(choices=[
        'hospital', 'clinic', 'nursing_home', 'dialysis_center', 'rehabilitation', 'other'
    ])
    street_address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    zip_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    pickup_instructions = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # Primary contact
    pc_full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    pc_title = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pc_department = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pc_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    pc_email = serializers.EmailField(required=False, allow_blank=True)

    # Billing contact
    bc_full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    bc_title = serializers.CharField(max_length=100, required=False, allow_blank=True)
    bc_department = serializers.CharField(max_length=100, required=False, allow_blank=True)
    bc_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    bc_email = serializers.EmailField(required=False, allow_blank=True)
    bc_insurance_no = serializers.CharField(max_length=100, required=False, allow_blank=True)

    # Contract
    contract_number = serializers.CharField(max_length=100)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    billing_cycle = serializers.ChoiceField(choices=['weekly', 'monthly'], default='monthly')
    payment_terms = serializers.CharField(max_length=50, required=False, allow_blank=True)
    volume_commitment = serializers.IntegerField(min_value=0, required=False, default=0)
    auto_renewal = serializers.BooleanField(required=False, default=False)

    # Pricing
    standard_sedan_rate = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, default=0)
    wheelchair_accessible_rate = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, default=0)
    stretcher_transport_rate = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, default=0)
    wait_time_rate = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, default=0)
    discount_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0)
    minimum_trips = serializers.IntegerField(min_value=0, required=False, default=0)

    # Tax
    tax_id = serializers.CharField(max_length=100, required=False, allow_blank=True)

    # Documents — optional at creation
    w9_tax_form = serializers.FileField(required=False, allow_null=True)
    hipaa_agreement = serializers.FileField(required=False, allow_null=True)
    insurance_certificate = serializers.FileField(required=False, allow_null=True)

    def validate_contract_number(self, value):
        from .models import FacilityContract
        if FacilityContract.objects.filter(contract_number=value).exists():
            raise serializers.ValidationError('This contract number is already in use.')
        return value

    def validate(self, attrs):
        # Contract date validation
        start = attrs.get('start_date')
        end = attrs.get('end_date')
        if start and end and start >= end:
            raise serializers.ValidationError({'end_date': 'end_date must be after start_date.'})

        # Rate values must be non-negative
        rate_fields = [
            'standard_sedan_rate', 'wheelchair_accessible_rate',
            'stretcher_transport_rate', 'wait_time_rate',
        ]
        for field in rate_fields:
            if attrs.get(field) is not None and attrs[field] < 0:
                raise serializers.ValidationError({field: 'Rate values must be non-negative.'})

        # Discount between 0 and 100
        discount = attrs.get('discount_percentage', 0)
        if discount < 0 or discount > 100:
            raise serializers.ValidationError(
                {'discount_percentage': 'Discount percentage must be between 0 and 100.'}
            )

        # File type validation
        doc_fields = ['w9_tax_form', 'hipaa_agreement', 'insurance_certificate']
        allowed_types = ['application/pdf', 'image/jpeg', 'image/png']
        for field in doc_fields:
            f = attrs.get(field)
            if f:
                if hasattr(f, 'content_type') and f.content_type not in allowed_types:
                    raise serializers.ValidationError({field: 'Only PDF, JPG, and PNG files are allowed.'})
                if f.size > 10 * 1024 * 1024:
                    raise serializers.ValidationError({field: 'File size must not exceed 10MB.'})

        return attrs


# Facility header serializer — GET /facilities/{id}/
class FacilityHeaderSerializer(serializers.ModelSerializer):

    class Meta:
        model = Facility
        fields = [
            'id', 'facility_name', 'facility_id', 'facility_type',
            'total_trips', 'total_trips_this_month',
            'total_revenue', 'total_revenue_this_month',
            'outstanding_amount', 'avg_payment_days',
            'status',
        ]


# Primary contact serializer
class FacilityPrimaryContactSerializer(serializers.ModelSerializer):

    class Meta:
        model = FacilityPrimaryContact
        exclude = ['id', 'facility']


# Billing contact serializer
class FacilityBillingContactSerializer(serializers.ModelSerializer):

    class Meta:
        model = FacilityBillingContact
        exclude = ['id', 'facility']


# Contract serializer
class FacilityContractSerializer(serializers.ModelSerializer):

    class Meta:
        model = FacilityContract
        exclude = ['id', 'facility']

    def validate(self, attrs):
        start = attrs.get('start_date')
        end = attrs.get('end_date')
        if start and end and start >= end:
            raise serializers.ValidationError({'end_date': 'end_date must be after start_date.'})
        return attrs


# Pricing serializer
class FacilityPricingSerializer(serializers.ModelSerializer):

    class Meta:
        model = FacilityPricing
        exclude = ['id', 'facility']

    def validate(self, attrs):
        rate_fields = [
            'standard_sedan_rate', 'wheelchair_accessible_rate',
            'stretcher_transport_rate', 'wait_time_rate',
        ]
        for field in rate_fields:
            if field in attrs and attrs[field] is not None and attrs[field] < 0:
                raise serializers.ValidationError({field: 'Rate values must be non-negative.'})

        discount = attrs.get('discount_percentage')
        if discount is not None and (discount < 0 or discount > 100):
            raise serializers.ValidationError(
                {'discount_percentage': 'Discount percentage must be between 0 and 100.'}
            )
        return attrs


# Tax serializer
class FacilityTaxSerializer(serializers.ModelSerializer):

    class Meta:
        model = FacilityTax
        exclude = ['id', 'facility']


# Document serializer
class FacilityDocumentSerializer(serializers.ModelSerializer):

    document_id = serializers.UUIDField(source='id')
    file = serializers.SerializerMethodField()

    class Meta:
        model = FacilityDocument
        fields = ['document_id', 'document_name', 'document_type', 'file', 'uploaded_date']

    def get_file(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


# Document upload serializer
class FacilityDocumentUploadSerializer(serializers.Serializer):

    document_name = serializers.CharField(max_length=255)
    document_type = serializers.ChoiceField(choices=[
        'w9_tax_form', 'hipaa_agreement', 'insurance_certificate', 'contract', 'other'
    ])
    file = serializers.FileField()

    def validate_file(self, value):
        allowed = ['application/pdf', 'image/jpeg', 'image/png']
        if hasattr(value, 'content_type') and value.content_type not in allowed:
            raise serializers.ValidationError('Only PDF, JPG, and PNG files are allowed.')
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('File size must not exceed 10MB.')
        return value