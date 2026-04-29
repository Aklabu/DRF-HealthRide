import re
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import Provider, ProviderSettings, RateCard


# Validate password strength — min 8 chars, at least one letter and one number
def validate_password_strength(value):
    if len(value) < 8:
        raise serializers.ValidationError('Password must be at least 8 characters.')
    if not re.search(r'[A-Za-z]', value):
        raise serializers.ValidationError('Password must contain at least one letter.')
    if not re.search(r'\d', value):
        raise serializers.ValidationError('Password must contain at least one number.')
    return value


# Step 1 of signup — collect email and password
class SignupInitiateSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=255)
    business_email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_business_email(self, value):
        if Provider.objects.filter(business_email=value).exists():
            raise serializers.ValidationError('This email is already registered.')
        return value

    def validate_password(self, value):
        return validate_password_strength(value)

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs


# Step 2 of signup — verify OTP
class SignupVerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)


# Step 3 of signup — complete business info
class SignupCompleteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    business_address = serializers.CharField()
    timezone = serializers.CharField(max_length=100)
    ein_tax_id = serializers.CharField(max_length=50)
    number_of_drivers = serializers.IntegerField(min_value=0)
    number_of_vehicles = serializers.IntegerField(min_value=0)

    def validate_timezone(self, value):
        import pytz
        if value not in pytz.all_timezones:
            raise serializers.ValidationError('Invalid timezone.')
        return value


# Signin — email + password
class SigninSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    remember_me = serializers.BooleanField(default=False)


# Signin OTP verification
class SigninVerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)


# Forgot password — request OTP
class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


# Forgot password — verify OTP
class ForgotPasswordVerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)


# Forgot password — reset with token
class ForgotPasswordResetSerializer(serializers.Serializer):
    reset_token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
    confirm_new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        return validate_password_strength(value)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_new_password']:
            raise serializers.ValidationError({'confirm_new_password': 'Passwords do not match.'})
        return attrs


# Token refresh
class TokenRefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


# Logout
class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


# Provider info returned after successful login
class ProviderProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = [
            'id', 'business_name', 'business_email', 'timezone',
            'contact_phone', 'company_logo', 'is_verified', 'created_at'
        ]


# Company profile — GET and PATCH
class CompanyProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = [
            'business_name', 'business_email', 'contact_phone',
            'business_hours', 'company_logo', 'service_area', 'coverage_zones',
            'ein_tax_id', 'business_license_number', 'insurance_provider',
            'insurance_policy_number', 'bonding_details'
        ]

    def validate_contact_phone(self, value):
        # Basic phone format validation — allow +, digits, spaces, dashes
        if value and not re.match(r'^[\+\d\s\-\(\)]{7,20}$', value):
            raise serializers.ValidationError('Invalid phone number format.')
        return value

    def validate_business_hours(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('business_hours must be a JSON object.')
        return value

    def validate_coverage_zones(self, value):
        if not isinstance(value, (dict, list)):
            raise serializers.ValidationError('coverage_zones must be a JSON object or array.')
        return value


# Platform settings — trip params, cancellation, notifications
class ProviderSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderSettings
        exclude = ['id', 'provider']

    def validate_default_trip_lead_time(self, value):
        if value < 0:
            raise serializers.ValidationError('Lead time must be a positive integer.')
        return value

    def validate_auto_assignment_radius(self, value):
        if value < 0:
            raise serializers.ValidationError('Radius must be a positive decimal.')
        return value

    def validate_cancellation_fee(self, value):
        if value < 0:
            raise serializers.ValidationError('Cancellation fee must be a positive decimal.')
        return value


# Rate card — standard, wheelchair, stretcher
class RateCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateCard
        exclude = ['id', 'provider']

    def validate(self, attrs):
        # All rate values must be non-negative
        for field, value in attrs.items():
            if value is not None and value < 0:
                raise serializers.ValidationError({field: 'Rate values must be non-negative.'})
        return attrs