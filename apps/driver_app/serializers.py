import re
from rest_framework import serializers


# ── Auth ──────────────────────────────────────────────────────────────────────

class DriverSigninSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    remember_me = serializers.BooleanField(default=False)


class DriverOTPVerifySerializer(serializers.Serializer):
    session_token = serializers.CharField()
    otp = serializers.CharField(min_length=4, max_length=4)


class DriverForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class DriverForgotPasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=4, max_length=4)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs


class DriverChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        if attrs['new_password'] == attrs['current_password']:
            raise serializers.ValidationError(
                {'new_password': 'New password must differ from current password.'}
            )
        return attrs


# ── Profile ───────────────────────────────────────────────────────────────────

class DriverBasicProfileSerializer(serializers.Serializer):
    full_name = serializers.CharField(read_only=True)
    profile_picture = serializers.ImageField(read_only=True)
    total_trips = serializers.IntegerField(read_only=True)


class DriverBasicProfileUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False)
    profile_picture = serializers.ImageField(required=False, allow_null=True)


class DriverContactProfileSerializer(serializers.Serializer):
    email = serializers.EmailField(read_only=True)
    phone_number = serializers.CharField(read_only=True)
    home_address = serializers.CharField(read_only=True)


class DriverContactUpdateSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20, required=False)
    home_address = serializers.CharField(required=False, allow_blank=True)

    def validate_phone_number(self, value):
        if value and not re.match(r'^[\+\d\s\-\(\)]{7,20}$', value):
            raise serializers.ValidationError('Invalid phone number format.')
        return value


class DriverDocumentSerializer(serializers.Serializer):
    document_type = serializers.CharField()
    document_number = serializers.CharField(allow_null=True)
    expire_date = serializers.DateField(allow_null=True)
    upload_date = serializers.DateField()
    file_url = serializers.CharField(allow_null=True)


class DriverDocumentUploadSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=[
        'driver_license', 'insurance', 'cpr_certificate', 'background_check',
    ])
    file = serializers.FileField()
    document_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    expire_date = serializers.DateField(required=False, allow_null=True)

    def validate_file(self, value):
        allowed = ['application/pdf', 'image/jpeg', 'image/png']
        if hasattr(value, 'content_type') and value.content_type not in allowed:
            raise serializers.ValidationError('Only PDF, JPG, and PNG files are allowed.')
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('File size must not exceed 10MB.')
        return value


class DriverVehicleUpdateSerializer(serializers.Serializer):
    vehicle_id = serializers.UUIDField()


# ── Dashboard ─────────────────────────────────────────────────────────────────

class TripScheduleItemSerializer(serializers.Serializer):
    trip_id = serializers.CharField()
    passenger_name = serializers.CharField(allow_null=True)
    passenger_image = serializers.CharField(allow_null=True)
    scheduled_time = serializers.TimeField()
    pickup_location = serializers.CharField()
    dropoff_location = serializers.CharField()
    distance_miles = serializers.DecimalField(max_digits=8, decimal_places=2)
    estimated_duration_minutes = serializers.IntegerField()
    trip_status = serializers.CharField(required=False)


# ── Trip actions ──────────────────────────────────────────────────────────────

class DriverStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['online', 'offline'])


class DriverLocationUpdateSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    heading = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True
    )
    speed = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True
    )


class TripSignatureUploadSerializer(serializers.Serializer):
    signature = serializers.ImageField()
