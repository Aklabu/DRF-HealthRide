from rest_framework import serializers
from django.utils import timezone
from .models import Vehicle, VehicleInsurance, VehicleMaintenance, VehicleDocument


# Serializer for vehicle list row
class VehicleListSerializer(serializers.ModelSerializer):

    assigned_driver_name = serializers.SerializerMethodField()
    assigned_driver_id = serializers.SerializerMethodField()
    vehicle_image = serializers.SerializerMethodField()
    compliance_status = serializers.SerializerMethodField()

    class Meta:
        model = Vehicle
        fields = [
            'id', 'license_plate', 'vehicle_type', 'status',
            'vehicle_image', 'assigned_driver_name', 'assigned_driver_id',
            'compliance_status',
        ]

    def get_assigned_driver_name(self, obj):
        if obj.assigned_driver:
            return obj.assigned_driver.full_name
        return None

    def get_assigned_driver_id(self, obj):
        if obj.assigned_driver:
            return str(obj.assigned_driver.id)
        return None

    def get_vehicle_image(self, obj):
        # Return first document image if available
        doc = obj.documents.filter(
            document_type__in=['registration', 'insurance']
        ).first()
        if doc and doc.file:
            return doc.file.url
        return None

    def get_compliance_status(self, obj):
        # Check if any document expires within 60 days
        threshold = timezone.now().date() + timezone.timedelta(days=60)
        expiring = obj.documents.filter(
            expires_date__isnull=False,
            expires_date__lte=threshold
        ).exists()
        if expiring:
            return 'expiring_soon'
        return 'compliant'


# Serializer for vehicle creation — basic info section
class VehicleCreateSerializer(serializers.Serializer):

    # Basic info
    brand = serializers.CharField(max_length=100)
    model_number = serializers.CharField(max_length=100)
    year = serializers.IntegerField(min_value=1900, max_value=2100)
    color = serializers.CharField(max_length=50)
    license_plate = serializers.CharField(max_length=20)
    vin_number = serializers.CharField(max_length=17)
    purchase_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    purchase_date = serializers.DateField(required=False, allow_null=True)

    # Features
    vehicle_type = serializers.ChoiceField(choices=['sedan', 'wheelchair_accessible', 'stretcher'])
    seating_capacity = serializers.IntegerField(min_value=1)
    accessibility_features = serializers.ChoiceField(choices=['standard', 'stretcher', 'oxygen', 'wheelchair'])
    ramp_type = serializers.ChoiceField(choices=['fold_out', 'roll_out', 'none'], required=False, default='none')
    securement_system = serializers.CharField(max_length=255, required=False, allow_blank=True)

    # Insurance
    insurance_provider = serializers.CharField(max_length=255, required=False, allow_blank=True)
    policy_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    monthly_premium = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, default=0)
    liability_coverage = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)
    collision_coverage = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)
    comprehensive_coverage = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)

    # Registration
    registration_state = serializers.CharField(max_length=50, required=False, allow_blank=True)
    registration_expiry = serializers.DateField(required=False, allow_null=True)

    # Maintenance setup
    current_mileage = serializers.IntegerField(min_value=0, required=False, default=0)
    service_interval = serializers.IntegerField(min_value=0, required=False, default=0)
    last_service_date = serializers.DateField(required=False, allow_null=True)
    last_service_mileage = serializers.IntegerField(min_value=0, required=False, default=0)

    # Assignment
    assigned_driver = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=['active', 'inactive', 'in_maintenance'], default='active')

    # Documents
    registration_document = serializers.FileField(required=False, allow_null=True)
    insurance_document = serializers.FileField(required=False, allow_null=True)

    def validate_vin_number(self, value):
        from .models import Vehicle
        if Vehicle.objects.filter(vin_number=value).exists():
            raise serializers.ValidationError('This VIN number is already registered.')
        return value

    def validate(self, attrs):
        # File type validation
        for field in ['registration_document', 'insurance_document']:
            file = attrs.get(field)
            if file:
                allowed = ['application/pdf', 'image/jpeg', 'image/png']
                if hasattr(file, 'content_type') and file.content_type not in allowed:
                    raise serializers.ValidationError({field: 'Only PDF, JPG, and PNG files are allowed.'})
                # Max 10MB
                if file.size > 10 * 1024 * 1024:
                    raise serializers.ValidationError({field: 'File size must not exceed 10MB.'})
        return attrs


# Serializer for vehicle header info
class VehicleHeaderSerializer(serializers.ModelSerializer):

    vehicle_name = serializers.SerializerMethodField()
    mileage = serializers.SerializerMethodField()
    capacity = serializers.IntegerField(source='seating_capacity')
    insurance = serializers.SerializerMethodField()
    assigned_driver = serializers.SerializerMethodField()

    class Meta:
        model = Vehicle
        fields = [
            'id', 'vehicle_name', 'vehicle_type', 'mileage', 'capacity',
            'insurance', 'assigned_driver', 'assigned_since', 'purchase_date',
            'status',
        ]

    def get_vehicle_name(self, obj):
        return f'{obj.brand} {obj.model_number}'

    def get_mileage(self, obj):
        # Get current mileage from latest maintenance record
        latest = obj.maintenance_records.first()
        return latest.current_mileage if latest else 0

    def get_insurance(self, obj):
        try:
            ins = obj.insurance
            return {
                'policy_number': ins.policy_number,
                'expiry_date': ins.expiry_date,
            }
        except VehicleInsurance.DoesNotExist:
            return None

    def get_assigned_driver(self, obj):
        if obj.assigned_driver:
            return {
                'name': obj.assigned_driver.full_name,
                'id': str(obj.assigned_driver.id),
            }
        return None


# Vehicle header update serializer, only allow certain fields to be updated
class VehicleHeaderUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Vehicle
        fields = [
            'brand', 'model_number', 'vehicle_type', 'seating_capacity',
            'purchase_date', 'status',
        ]

    # Read-only fields — reject if submitted
    READ_ONLY = ['id', 'total_trips', 'total_hours', 'avg_fuel_economy', 'total_revenue']

    def validate(self, attrs):
        for field in self.READ_ONLY:
            if field in self.initial_data:
                raise serializers.ValidationError({field: 'This field is read-only.'})
        return attrs


# Serializer for specifications
class VehicleSpecificationsSerializer(serializers.ModelSerializer):

    class Meta:
        model = Vehicle
        fields = [
            'model_number', 'year', 'color', 'vin_number', 'license_plate',
            'purchase_date', 'accessibility_features', 'seating_capacity',
            'ramp_type', 'securement_system', 'registration_state', 'registration_expiry',
            # Read-only inspection fields
            'last_inspection', 'next_due', 'inspector',
        ]
        read_only_fields = ['last_inspection', 'next_due', 'inspector']

    def validate_vin_number(self, value):
        # Allow same VIN on update (skip check if same vehicle)
        instance = self.instance
        if Vehicle.objects.filter(vin_number=value).exclude(id=instance.id).exists():
            raise serializers.ValidationError('This VIN number is already registered.')
        return value


# Serializer for VehicleInsurance
class VehicleInsuranceSerializer(serializers.ModelSerializer):

    class Meta:
        model = VehicleInsurance
        exclude = ['id', 'vehicle']


# Serializer for maintenance records list
class VehicleMaintenanceSerializer(serializers.ModelSerializer):

    class Meta:
        model = VehicleMaintenance
        fields = [
            'id', 'maintenance_type', 'scheduled_date', 'completed_date',
            'mileage_at_service', 'notes', 'next_service_date', 'next_service_mileage',
        ]


# Serializer for document list
class VehicleDocumentSerializer(serializers.ModelSerializer):

    file = serializers.SerializerMethodField()

    class Meta:
        model = VehicleDocument
        fields = ['id', 'document_name', 'document_type', 'file', 'uploaded_date', 'expires_date']

    def get_file(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


# Serializer for document upload
class VehicleDocumentUploadSerializer(serializers.Serializer):

    document_name = serializers.CharField(max_length=255)
    document_type = serializers.ChoiceField(choices=['registration', 'insurance', 'inspection', 'other'])
    file = serializers.FileField()
    expires_date = serializers.DateField(required=False, allow_null=True)

    def validate_file(self, value):
        allowed_types = ['application/pdf', 'image/jpeg', 'image/png']
        if hasattr(value, 'content_type') and value.content_type not in allowed_types:
            raise serializers.ValidationError('Only PDF, JPG, and PNG files are allowed.')
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('File size must not exceed 10MB.')
        return value


# Serializer for driver assignment
class AssignDriverSerializer(serializers.Serializer):

    driver_id = serializers.UUIDField(allow_null=True)