from rest_framework import serializers
from .models import PreTripInspection, ComplianceDocument, ComplianceAlert, InspectionSchedule


# PreTripInspection serializers List
class InspectionListSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    vehicle_number = serializers.SerializerMethodField()

    class Meta:
        model = PreTripInspection
        fields = [
            'id', 'status', 'driver_name', 'vehicle_number',
            'odometer', 'fuel_level', 'date_time',
        ]

    def get_driver_name(self, obj):
        return obj.driver.full_name if obj.driver else None

    def get_vehicle_number(self, obj):
        return obj.vehicle.license_plate if obj.vehicle else None


# PreTripInspection serializers Detail and Create
class InspectionDetailSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    vehicle_number = serializers.SerializerMethodField()
    issue_photo = serializers.SerializerMethodField()
    signature = serializers.SerializerMethodField()

    class Meta:
        model = PreTripInspection
        fields = [
            'id', 'date_time', 'driver_name', 'vehicle_number',
            'odometer', 'fuel_level', 'signature',
            'vehicle_exterior', 'vehicle_interior', 'tires', 'brakes',
            'fluids', 'lights', 'safety_equipment', 'cleanliness',
            'wheelchair_ramp', 'dashboard_warning_lights',
            'issue_description', 'issue_photo',
            'status',
        ]

    def get_driver_name(self, obj):
        return obj.driver.full_name if obj.driver else None

    def get_vehicle_number(self, obj):
        return obj.vehicle.license_plate if obj.vehicle else None

    def get_issue_photo(self, obj):
        request = self.context.get('request')
        if obj.issue_photo and request:
            return request.build_absolute_uri(obj.issue_photo.url)
        return None

    def get_signature(self, obj):
        request = self.context.get('request')
        if obj.signature and request:
            return request.build_absolute_uri(obj.signature.url)
        return None


# Serializer for creating a new PreTripInspection record from driver app submissions
class InspectionCreateSerializer(serializers.Serializer):
    driver = serializers.UUIDField()
    vehicle = serializers.UUIDField()
    odometer = serializers.IntegerField(min_value=0)
    fuel_level = serializers.ChoiceField(
        choices=['full', 'three_quarters', 'half', 'quarter', 'low']
    )
    vehicle_exterior = serializers.ChoiceField(choices=['pass', 'fail'])
    vehicle_interior = serializers.ChoiceField(choices=['pass', 'fail'])
    tires = serializers.ChoiceField(choices=['pass', 'fail'])
    brakes = serializers.ChoiceField(choices=['pass', 'fail'])
    fluids = serializers.ChoiceField(choices=['pass', 'fail'])
    lights = serializers.ChoiceField(choices=['pass', 'fail'])
    safety_equipment = serializers.ChoiceField(choices=['pass', 'fail'])
    cleanliness = serializers.ChoiceField(choices=['pass', 'fail'])
    wheelchair_ramp = serializers.ChoiceField(
        choices=['pass', 'fail', 'not_applicable'], default='not_applicable'
    )
    dashboard_warning_lights = serializers.ChoiceField(choices=['pass', 'fail'])
    issue_description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    issue_photo = serializers.FileField(required=False, allow_null=True)
    signature = serializers.FileField()

    def validate(self, attrs):
        # Checklist fields that can be pass/fail (exclude wheelchair_ramp)
        checklist_fields = [
            'vehicle_exterior', 'vehicle_interior', 'tires', 'brakes',
            'fluids', 'lights', 'safety_equipment', 'cleanliness',
            'dashboard_warning_lights',
        ]
        has_failure = any(attrs.get(f) == 'fail' for f in checklist_fields)
        if attrs.get('wheelchair_ramp') == 'fail':
            has_failure = True

        if has_failure and not attrs.get('issue_description'):
            raise serializers.ValidationError(
                {'issue_description': 'issue_description is required when any checklist item fails.'}
            )
        return attrs


# Serializer for admin corrections to existing PreTripInspection records
class InspectionPatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = PreTripInspection
        fields = ['issue_description', 'issue_photo']


# ComplianceDocument serializers List 
class ComplianceDocumentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceDocument
        fields = [
            'id', 'document_type', 'holder_name', 'holder_type',
            'document_number', 'expiration_date',
            'days_until_expiration', 'status',
        ]


class ComplianceDocumentDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceDocument
        fields = [
            'id', 'holder_type', 'holder_id', 'holder_name',
            'document_type', 'document_number',
            'file_reference', 'upload_date', 'expiration_date',
            'status', 'days_until_expiration',
            'last_checked_at', 'is_active', 'created_at', 'updated_at',
        ]


class ComplianceDocumentCreateSerializer(serializers.Serializer):
    # Used by internal service calls from drivers/vehicles apps.
    holder_type = serializers.ChoiceField(choices=['driver', 'vehicle'])
    holder_id = serializers.UUIDField()
    holder_name = serializers.CharField(max_length=255)
    document_type = serializers.ChoiceField(choices=[
        'driver_license', 'insurance', 'cpr_certificate', 'background_check',
        'vehicle_registration', 'vehicle_insurance', 'w9', 'hipaa_agreement', 'others',
    ])
    document_number = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    upload_date = serializers.DateField()
    expiration_date = serializers.DateField(required=False, allow_null=True)
    file_reference = serializers.CharField(required=False, allow_blank=True)


class ComplianceDocumentUpdateSerializer(serializers.Serializer):
    # Used on document renewal.
    document_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    expiration_date = serializers.DateField(required=False, allow_null=True)
    upload_date = serializers.DateField(required=False)
    file_reference = serializers.CharField(required=False, allow_blank=True)


# ComplianceAlert serializers List and Detail
class ComplianceAlertListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceAlert
        fields = [
            'id', 'severity', 'alert_type', 'title', 'description',
            'holder_name', 'holder_type',
            'days_remaining', 'due_date', 'is_resolved', 'created_at',
        ]


class ComplianceAlertDetailSerializer(serializers.ModelSerializer):
    related_document = ComplianceDocumentListSerializer(read_only=True)
    related_inspection = InspectionListSerializer(read_only=True)

    class Meta:
        model = ComplianceAlert
        fields = [
            'id', 'severity', 'alert_type', 'title', 'description',
            'holder_name', 'holder_type', 'holder_id',
            'days_remaining', 'due_date',
            'related_document', 'related_inspection',
            'is_resolved', 'resolved_at', 'created_at',
        ]
