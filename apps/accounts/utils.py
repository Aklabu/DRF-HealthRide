import hashlib
import random
import string
import secrets
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken
from .models import OTPVerification


# Generate a 6-digit numeric OTP
def generate_otp():
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])


# Hash OTP using SHA-256 before storing in DB
def hash_otp(otp_code):
    return hashlib.sha256(otp_code.encode()).hexdigest()


# Invalidate all unused OTPs for a given email and purpose
def invalidate_existing_otps(email, purpose):
    OTPVerification.objects.filter(
        email=email,
        purpose=purpose,
        is_used=False
    ).update(is_used=True)


# Create and store a new OTP record — returns the plain OTP for sending
def create_otp(email, purpose):
    # Invalidate any old OTPs first
    invalidate_existing_otps(email, purpose)

    otp_plain = generate_otp()
    otp_hashed = hash_otp(otp_plain)

    OTPVerification.objects.create(
        email=email,
        otp_code=otp_hashed,
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=10)
    )
    return otp_plain


# Verify submitted OTP against stored hash — returns OTPVerification or None
def verify_otp(email, purpose, submitted_otp):
    otp_hashed = hash_otp(submitted_otp)
    try:
        otp_record = OTPVerification.objects.filter(
            email=email,
            purpose=purpose,
            is_used=False
        ).latest('created_at')
    except OTPVerification.DoesNotExist:
        return None, 'No OTP found for this email.'

    if otp_record.is_expired():
        return None, 'OTP has expired.'

    if otp_record.otp_code != otp_hashed:
        return None, 'Invalid OTP.'

    return otp_record, None


# Generate JWT tokens for a provider
def get_tokens_for_provider(provider, remember_me=False):
    refresh = RefreshToken.for_user(provider)

    # Extend refresh token lifetime if remember_me is True
    if remember_me:
        refresh.set_exp(lifetime=timedelta(days=30))

    return {
        'access_token': str(refresh.access_token),
        'refresh_token': str(refresh),
    }


# Generate a signed password reset token using secrets
def generate_reset_token():
    return secrets.token_urlsafe(32)


# Store reset token in cache with 15-minute expiry
def store_reset_token(email, token):
    from django.core.cache import cache
    cache_key = f'password_reset_{token}'
    # Store email against token for 15 minutes
    cache.set(cache_key, email, timeout=900)


# Retrieve and validate reset token from cache — returns email or None
def validate_reset_token(token):
    from django.core.cache import cache
    cache_key = f'password_reset_{token}'
    email = cache.get(cache_key)
    return email


# Invalidate reset token after use
def invalidate_reset_token(token):
    from django.core.cache import cache
    cache_key = f'password_reset_{token}'
    cache.delete(cache_key)