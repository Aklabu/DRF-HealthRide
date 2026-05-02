from rest_framework import serializers
from .models import (
    Passenger, PassengerMedical, PassengerEmergencyContact,
    PassengerInsurance, PassengerCommonLocation, PassengerFacility, PreferredDriver,
)


# Passenger list row serializer
class PassengerListSerializer(serializers.ModelSerializer):

    name = serializers.SerializerMethodField()
    contact_number = serializers.CharField(source='phone_number')
    contact_email = serializers.EmailField(source='email')
    insurance_type = serializers.SerializerMethodField()
    insurance_id = serializers.SerializerMethodField()

    class Meta:
        model = Passenger
        fields = [
            'id', 'name', 'profile_picture', 'contact_number', 'contact_email',
            'mobility', 'insurance_type', 'insurance_id',
            'total_trips', 'completed_trips', 'status',
        ]

    def get_name(self, obj):
        return obj.full_name

    def get_insurance_type(self, obj):
        try:
            return obj.insurance.insurance_provider
        except PassengerInsurance.DoesNotExist:
            return None

    def get_insurance_id(self, obj):
        try:
            return obj.insurance.policy_number
        except PassengerInsurance.DoesNotExist:
            return None


# Passenger creation serializer
class PassengerCreateSerializer(serializers.Serializer):

    # Basic info
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    phone_number = serializers.CharField(max_length=20)
    email = serializers.EmailField()
    preferred_language = serializers.CharField(max_length=50, required=False, allow_blank=True)

    # Address
    street_address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    apartment = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    zip_code = serializers.CharField(max_length=20, required=False, allow_blank=True)

    # Common locations — max 2 at creation
    common_locations = serializers.ListField(
        child=serializers.DictField(), required=False, default=list, max_length=2
    )

    # Medical
    special_requirements = serializers.ChoiceField(
        choices=['standard', 'stretcher', 'oxygen', 'wheelchair'], default='standard'
    )
    medical_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    special_assistance_needs = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # Emergency contact
    ec_full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    ec_phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    ec_email = serializers.EmailField(required=False, allow_blank=True)
    ec_relation = serializers.ChoiceField(
        choices=['self', 'father', 'mother', 'other'], required=False, default='other'
    )
    ec_home_address = serializers.CharField(required=False, allow_blank=True)

    # Insurance
    insurance_provider = serializers.CharField(max_length=255, required=False, allow_blank=True)
    policy_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    medicare_number = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    medicaid_number = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    effective_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)

    # Facilities — array of UUIDs
    facilities = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )

    def validate_common_locations(self, value):
        for loc in value:
            if 'location_name' not in loc or 'full_address' not in loc:
                raise serializers.ValidationError(
                    'Each location must include location_name and full_address.'
                )
        return value


# Passenger header serializer
class PassengerHeaderSerializer(serializers.ModelSerializer):

    name = serializers.SerializerMethodField()
    home_address = serializers.SerializerMethodField()

    class Meta:
        model = Passenger
        fields = [
            'id', 'name', 'profile_picture',
            'phone_number', 'email', 'date_of_birth', 'home_address',
            'mobility', 'preferred_language',
            'total_trips', 'completed_trips',
            'total_spent', 'outstanding_balance',
            'status',
        ]
        read_only_fields = ['total_trips', 'completed_trips', 'total_spent', 'outstanding_balance']

    def get_name(self, obj):
        return obj.full_name

    def get_home_address(self, obj):
        return obj.home_address


# Passenger header update serializer
class PassengerHeaderUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Passenger
        fields = [
            'first_name', 'last_name', 'date_of_birth',
            'phone_number', 'email', 'profile_picture', 'preferred_language',
            'street_address', 'apartment', 'city', 'state', 'zip_code',
            'mobility', 'status',
        ]

    def validate_email(self, value):
        # Email unique within same provider
        instance = self.instance
        qs = Passenger.objects.filter(provider=instance.provider, email=value).exclude(id=instance.id)
        if qs.exists():
            raise serializers.ValidationError('A passenger with this email already exists under your account.')
        return value

    def validate_phone_number(self, value):
        # Phone unique within same provider
        instance = self.instance
        qs = Passenger.objects.filter(provider=instance.provider, phone_number=value).exclude(id=instance.id)
        if qs.exists():
            raise serializers.ValidationError('A passenger with this phone number already exists under your account.')
        return value


# Emergency contact serializer
class PassengerEmergencyContactSerializer(serializers.ModelSerializer):

    class Meta:
        model = PassengerEmergencyContact
        exclude = ['id', 'passenger']


# Common location serializer
class PassengerCommonLocationSerializer(serializers.ModelSerializer):

    class Meta:
        model = PassengerCommonLocation
        fields = ['id', 'location_name', 'full_address', 'trips_count']


# Preferred driver serializer
class PreferredDriverSerializer(serializers.ModelSerializer):

    driver_name = serializers.CharField(source='driver.full_name')
    driver_image = serializers.SerializerMethodField()

    class Meta:
        model = PreferredDriver
        fields = ['driver_name', 'driver_image', 'trips_count']

    def get_driver_image(self, obj):
        request = self.context.get('request')
        if obj.driver.profile_picture and request:
            return request.build_absolute_uri(obj.driver.profile_picture.url)
        return None


# Medical serializer
class PassengerMedicalSerializer(serializers.ModelSerializer):

    class Meta:
        model = PassengerMedical
        exclude = ['id', 'passenger']


# Insurance serializer
class PassengerInsuranceSerializer(serializers.ModelSerializer):

    class Meta:
        model = PassengerInsurance
        exclude = ['id', 'passenger']


# Overview PATCH — common location update item
class CommonLocationUpdateSerializer(serializers.Serializer):

    id = serializers.UUIDField(required=False, allow_null=True)
    location_name = serializers.CharField(max_length=255, required=False)
    full_address = serializers.CharField(required=False)
    delete = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        # New location — must have name and address
        if not attrs.get('id') and not attrs.get('delete'):
            if not attrs.get('location_name') or not attrs.get('full_address'):
                raise serializers.ValidationError(
                    'location_name and full_address are required for new locations.'
                )
        return attrs


# Medical PATCH serializer
class PassengerMedicalUpdateSerializer(serializers.Serializer):

    special_requirements = serializers.ChoiceField(
        choices=['standard', 'stretcher', 'oxygen', 'wheelchair'], required=False
    )
    medical_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    special_assistance_needs = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    add_facilities = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    remove_facilities = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )