from rest_framework import serializers
from django.utils import timezone
from .models import (
    Driver, DriverLicense, DriverEmergencyContact,
    DriverCertification, DriverDocument, DriverAvailability,
    DriverWorkLog, DriverPayout,
)

# Day name map for display
DAY_NAMES = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}


# Driver list row serializer
class DriverListSerializer(serializers.ModelSerializer):

    vehicle_number = serializers.SerializerMethodField()
    vehicle_type = serializers.SerializerMethodField()
    earnings_this_week = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = [
            'id', 'full_name', 'phone_number', 'email',
            'vehicle_number', 'vehicle_type',
            'earnings_this_week', 'total_trips',
            'status_employment', 'status_availability',
        ]

    def get_vehicle_number(self, obj):
        if obj.vehicle:
            return obj.vehicle.license_plate
        return None

    def get_vehicle_type(self, obj):
        if obj.vehicle:
            return obj.vehicle.vehicle_type
        return None

    def get_earnings_this_week(self, obj):
        # Current Mon–Sun window
        today = timezone.now().date()
        monday = today - timezone.timedelta(days=today.weekday())
        sunday = monday + timezone.timedelta(days=6)
        total = obj.work_logs.filter(
            date__gte=monday, date__lte=sunday
        ).aggregate(total=serializers.DecimalField)
        # Use values sum directly
        from django.db.models import Sum
        result = obj.work_logs.filter(
            date__gte=monday, date__lte=sunday
        ).aggregate(total=Sum('earnings'))
        return result['total'] or '0.00'


# Driver creation serializer
class DriverCreateSerializer(serializers.Serializer):

    # Basic info
    full_name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=20)
    email = serializers.EmailField()
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    home_address = serializers.CharField(required=False, allow_blank=True)

    # License
    license_number = serializers.CharField(max_length=100)
    license_state = serializers.CharField(max_length=50)
    license_expiry_date = serializers.DateField(required=False, allow_null=True)

    # Vehicle
    vehicle_id = serializers.UUIDField(required=False, allow_null=True)

    # Employment
    employment_start_date = serializers.DateField(required=False, allow_null=True)
    status_employment = serializers.ChoiceField(choices=['active', 'on_leave'], default='active')
    hourly_rate = serializers.DecimalField(max_digits=8, decimal_places=2, default=0)

    # Emergency contact
    emergency_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    emergency_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    emergency_relationship = serializers.CharField(max_length=100, required=False, allow_blank=True)

    # Certifications
    cpr_expiry_date = serializers.DateField(required=False, allow_null=True)
    cpr_is_active = serializers.BooleanField(required=False, default=False)
    first_aid_expiry_date = serializers.DateField(required=False, allow_null=True)
    first_aid_is_active = serializers.BooleanField(required=False, default=False)
    wheelchair_assistance = serializers.BooleanField(required=False, default=False)
    defensive_driving = serializers.BooleanField(required=False, default=False)

    # Documents — all optional at creation
    driver_license_file = serializers.FileField(required=False, allow_null=True)
    insurance_file = serializers.FileField(required=False, allow_null=True)
    cpr_certificate_file = serializers.FileField(required=False, allow_null=True)
    background_check_file = serializers.FileField(required=False, allow_null=True)

    # Availability — array of 7 day objects
    availability = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )

    def validate_email(self, value):
        if Driver.objects.filter(email=value).exists():
            raise serializers.ValidationError('A driver with this email already exists.')
        return value

    def validate_license_number(self, value):
        from .models import DriverLicense
        if DriverLicense.objects.filter(license_number=value).exists():
            raise serializers.ValidationError('This license number is already registered.')
        return value

    def validate(self, attrs):
        # Validate document file types and sizes
        doc_fields = ['driver_license_file', 'insurance_file', 'cpr_certificate_file', 'background_check_file']
        allowed_types = ['application/pdf', 'image/jpeg', 'image/png']
        for field in doc_fields:
            file = attrs.get(field)
            if file:
                if hasattr(file, 'content_type') and file.content_type not in allowed_types:
                    raise serializers.ValidationError({field: 'Only PDF, JPG, and PNG files are allowed.'})
                if file.size > 10 * 1024 * 1024:
                    raise serializers.ValidationError({field: 'File size must not exceed 10MB.'})

        # Validate availability array structure
        for day in attrs.get('availability', []):
            if 'day_of_week' not in day:
                raise serializers.ValidationError({'availability': 'Each day object must include day_of_week.'})
            if day.get('is_available') and (not day.get('start_time') or not day.get('end_time')):
                raise serializers.ValidationError({'availability': 'start_time and end_time are required when is_available is true.'})

        return attrs


# Driver header serializer for driver dashboard
class DriverHeaderSerializer(serializers.ModelSerializer):

    license = serializers.SerializerMethodField()
    vehicle = serializers.SerializerMethodField()
    this_week_earnings = serializers.SerializerMethodField()
    total_working_hours = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = [
            'id', 'full_name', 'profile_picture', 'joined_date',
            'status_employment', 'status_availability',
            'phone_number', 'email', 'home_address', 'last_active',
            'license', 'vehicle',
            'total_trips', 'on_time_rate',
            'this_week_earnings', 'total_working_hours',
        ]

    def get_license(self, obj):
        try:
            lic = obj.license
            return {
                'license_number': lic.license_number,
                'license_state': lic.license_state,
                'license_expiry_date': lic.license_expiry_date,
            }
        except Exception:
            return None

    def get_vehicle(self, obj):
        if obj.vehicle:
            return {
                'vehicle_id': str(obj.vehicle.id),
                'vehicle_type': obj.vehicle.vehicle_type,
            }
        return None

    def get_this_week_earnings(self, obj):
        from django.db.models import Sum
        today = timezone.now().date()
        monday = today - timezone.timedelta(days=today.weekday())
        sunday = monday + timezone.timedelta(days=6)
        result = obj.work_logs.filter(date__gte=monday, date__lte=sunday).aggregate(total=Sum('earnings'))
        return result['total'] or '0.00'

    def get_total_working_hours(self, obj):
        from django.db.models import Sum
        result = obj.work_logs.aggregate(total=Sum('hours_worked'))
        return result['total'] or '0.00'


# Driver header update serializer 
class DriverHeaderUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Driver
        fields = [
            'full_name', 'phone_number', 'email', 'home_address',
            'profile_picture', 'status_employment', 'status_availability',
            'last_active', 'hourly_rate',
        ]

    def validate_email(self, value):
        # Global uniqueness check — skip current driver
        qs = Driver.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError('A driver with this email already exists.')
        return value


# Emergency contact serializer
class DriverEmergencyContactSerializer(serializers.ModelSerializer):

    class Meta:
        model = DriverEmergencyContact
        exclude = ['id', 'driver']


# Certification serializer
class DriverCertificationSerializer(serializers.ModelSerializer):

    class Meta:
        model = DriverCertification
        fields = ['cert_type', 'expiry_date', 'is_active']


# Document serializer — returns file URL
class DriverDocumentSerializer(serializers.ModelSerializer):

    file = serializers.SerializerMethodField()

    class Meta:
        model = DriverDocument
        fields = ['id', 'document_type', 'file', 'upload_date', 'expire_date']

    def get_file(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


# Document upload serializer 
class DriverDocumentUploadSerializer(serializers.Serializer):

    document_type = serializers.ChoiceField(
        choices=['driver_license', 'insurance', 'cpr_certificate', 'background_check']
    )
    file = serializers.FileField()
    expire_date = serializers.DateField(required=False, allow_null=True)

    def validate_file(self, value):
        allowed = ['application/pdf', 'image/jpeg', 'image/png']
        if hasattr(value, 'content_type') and value.content_type not in allowed:
            raise serializers.ValidationError('Only PDF, JPG, and PNG files are allowed.')
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('File size must not exceed 10MB.')
        return value


# Availability serializer
class DriverAvailabilitySerializer(serializers.ModelSerializer):

    day = serializers.SerializerMethodField()

    class Meta:
        model = DriverAvailability
        fields = ['day_of_week', 'day', 'is_available', 'start_time', 'end_time']

    def get_day(self, obj):
        return DAY_NAMES.get(obj.day_of_week, '')


# Availability update item serializer
class AvailabilityUpdateItemSerializer(serializers.Serializer):

    day_of_week = serializers.IntegerField(min_value=0, max_value=6)
    is_available = serializers.BooleanField()
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time = serializers.TimeField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs['is_available']:
            if not attrs.get('start_time') or not attrs.get('end_time'):
                raise serializers.ValidationError('start_time and end_time are required when is_available is true.')
            if attrs['start_time'] >= attrs['end_time']:
                raise serializers.ValidationError('start_time must be before end_time.')
        return attrs


# Work log serializer
class DriverWorkLogSerializer(serializers.ModelSerializer):

    day = serializers.SerializerMethodField()

    class Meta:
        model = DriverWorkLog
        fields = ['date', 'day', 'hours_worked', 'trips_completed', 'earnings', 'status']

    def get_day(self, obj):
        return DAY_NAMES.get(obj.date.weekday(), '')


# Payout serializer
class DriverPayoutSerializer(serializers.ModelSerializer):

    payout_id = serializers.UUIDField(source='id')

    class Meta:
        model = DriverPayout
        fields = ['payout_id', 'from_date', 'to_date', 'total_hours', 'total_amount', 'created_at']


# Payout create serializer
class DriverPayoutCreateSerializer(serializers.Serializer):

    from_date = serializers.DateField()
    to_date = serializers.DateField()
    confirm = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if attrs['from_date'] >= attrs['to_date']:
            raise serializers.ValidationError({'to_date': 'to_date must be after from_date.'})
        return attrs