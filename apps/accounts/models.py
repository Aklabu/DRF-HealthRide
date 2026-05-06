import uuid
import pytz
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from datetime import timedelta


# Timezone choices from pytz
TIMEZONE_CHOICES = [(tz, tz) for tz in pytz.all_timezones]


# Custom manager for Provider model
class ProviderManager(BaseUserManager):

    def create_user(self, business_email, password=None, **extra_fields):
        if not business_email:
            raise ValueError('Business email is required')
        business_email = self.normalize_email(business_email)
        user = self.model(business_email=business_email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, business_email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_verified', True)
        return self.create_user(business_email, password, **extra_fields)


# Main provider model — one per NEMT business
class Provider(AbstractBaseUser, PermissionsMixin):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Authentication fields
    business_email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)   # required for Django admin access
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Business info fields
    business_name = models.CharField(max_length=255, blank=True)
    business_address = models.TextField(blank=True)
    timezone = models.CharField(max_length=100, choices=TIMEZONE_CHOICES, default='UTC')
    ein_tax_id = models.CharField(max_length=50, blank=True)
    number_of_drivers = models.PositiveIntegerField(default=0)
    number_of_vehicles = models.PositiveIntegerField(default=0)

    # Company profile fields
    company_logo = models.ImageField(upload_to='provider/logos/', null=True, blank=True)
    service_area = models.TextField(blank=True)
    coverage_zones = models.JSONField(default=dict, blank=True)
    business_hours = models.JSONField(default=dict, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)

    # Legal & compliance fields
    business_license_number = models.CharField(max_length=100, blank=True)
    insurance_provider = models.CharField(max_length=255, blank=True)
    insurance_policy_number = models.CharField(max_length=100, blank=True)
    bonding_details = models.TextField(blank=True)

    USERNAME_FIELD = 'business_email'
    REQUIRED_FIELDS = []

    objects = ProviderManager()

    class Meta:
        db_table = 'providers'

    def __str__(self):
        return self.business_email


# OTP verification for signup, login, and forgot password flows
class OTPVerification(models.Model):

    PURPOSE_CHOICES = [
        ('signup', 'Signup'),
        ('login', 'Login'),
        ('forgot_password', 'Forgot Password'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    otp_code = models.CharField(max_length=128)  # hashed before storage
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = 'otp_verifications'

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f'{self.email} - {self.purpose}'


# Provider platform and trip settings
class ProviderSettings(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='settings')

    # Trip parameters
    default_trip_lead_time = models.PositiveIntegerField(default=60)
    auto_assignment_radius = models.DecimalField(max_digits=6, decimal_places=2, default=10.00)
    enable_auto_assignment = models.BooleanField(default=False)

    # Cancellation policy
    cancellation_window = models.PositiveIntegerField(default=24)
    cancellation_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    # Notification preferences
    notify_trip_updates = models.BooleanField(default=True)
    notify_driver_alerts = models.BooleanField(default=True)
    notify_passenger_messages = models.BooleanField(default=True)
    notify_financial_alerts = models.BooleanField(default=True)

    class Meta:
        db_table = 'provider_settings'

    def __str__(self):
        return f'Settings for {self.provider.business_email}'


# Rate card for each provider — standard, wheelchair, stretcher
class RateCard(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='rate_card')

    # Standard sedan rates
    standard_base_fare = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    standard_miles_included = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    standard_per_mile_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)

    # Wheelchair accessible rates
    wheelchair_base_fare = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    wheelchair_miles_included = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    wheelchair_per_mile_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)

    # Stretcher transport rates
    stretcher_base_fare = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    stretcher_miles_included = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    stretcher_per_mile_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'rate_cards'

    def __str__(self):
        return f'Rate card for {self.provider.business_email}'