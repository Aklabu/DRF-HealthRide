"""
Driver-specific JWT authentication.

Driver tokens carry a `driver_id` claim in the payload so the driver_app
views can identify the driver without a separate lookup table.

The standard JWTAuthentication class is reused — we only override
`get_user()` to resolve a Driver instead of a Provider.
"""
import secrets
import hashlib
from datetime import timedelta

from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed


# ── OTP helpers ───────────────────────────────────────────────────────────────

def _otp_cache_key(driver_id):
    return f'driver_otp_{driver_id}'


def _session_cache_key(session_token):
    return f'driver_session_{session_token}'


def _failed_attempts_key(driver_id):
    return f'driver_otp_attempts_{driver_id}'


def generate_driver_otp(driver_id):
    """Generate a 4-digit OTP, store hashed in Redis for 10 minutes."""
    import random
    otp = str(random.randint(1000, 9999))
    hashed = hashlib.sha256(otp.encode()).hexdigest()
    cache.set(_otp_cache_key(str(driver_id)), hashed, timeout=600)
    return otp


def verify_driver_otp(driver_id, submitted_otp):
    """
    Verify submitted OTP against stored hash.
    Returns (True, None) on success or (False, error_message) on failure.
    Increments failed attempt counter — locks out after 3 failures.
    """
    driver_id = str(driver_id)
    attempts_key = _failed_attempts_key(driver_id)
    attempts = cache.get(attempts_key, 0)

    if attempts >= 3:
        return False, 'Too many failed attempts. Please restart sign-in.'

    stored_hash = cache.get(_otp_cache_key(driver_id))
    if not stored_hash:
        return False, 'OTP has expired. Please request a new one.'

    submitted_hash = hashlib.sha256(submitted_otp.encode()).hexdigest()
    if submitted_hash != stored_hash:
        cache.set(attempts_key, attempts + 1, timeout=600)
        remaining = 2 - attempts
        return False, f'Invalid OTP. {remaining} attempt(s) remaining.'

    # Success — clear OTP and attempt counter
    cache.delete(_otp_cache_key(driver_id))
    cache.delete(attempts_key)
    return True, None


def create_session_token(driver_id, remember_me=False):
    """
    Issue a short-lived session token (not a full JWT) to identify the
    pending OTP session between signin and verify-otp steps.
    """
    token = secrets.token_urlsafe(32)
    payload = {'driver_id': str(driver_id), 'remember_me': remember_me}
    cache.set(_session_cache_key(token), payload, timeout=600)
    return token


def resolve_session_token(session_token):
    """Return session payload dict or None if invalid/expired."""
    return cache.get(_session_cache_key(session_token))


def invalidate_session_token(session_token):
    cache.delete(_session_cache_key(session_token))


# ── JWT token generation for drivers ─────────────────────────────────────────

def get_tokens_for_driver(driver, remember_me=False):
    """
    Issue JWT access + refresh tokens for a driver.
    Embeds `driver_id` in the payload so other apps can identify the driver
    from the token without a separate DB lookup.
    """
    refresh = RefreshToken()
    refresh['driver_id'] = str(driver.id)
    refresh['provider_id'] = str(driver.provider.id)
    refresh['token_type'] = 'driver'

    if remember_me:
        refresh.set_exp(lifetime=timedelta(days=30))

    return {
        'access_token': str(refresh.access_token),
        'refresh_token': str(refresh),
    }


# ── Custom authentication backend for driver JWT ──────────────────────────────

class DriverJWTAuthentication(JWTAuthentication):
    """
    Extends JWTAuthentication to resolve a Driver from the `driver_id` claim
    instead of the standard `user_id` claim.

    Used as the authentication class on all driver_app views.
    The resolved Driver is attached to request.driver (not request.user,
    which remains the Provider for provider-facing views).
    """

    def get_user(self, validated_token):
        driver_id = validated_token.get('driver_id')
        if not driver_id:
            raise InvalidToken('Token does not contain driver_id claim.')

        try:
            from apps.drivers.models import Driver
            return Driver.objects.select_related('provider', 'vehicle').get(id=driver_id)
        except Exception:
            raise AuthenticationFailed('Driver not found or inactive.')

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        driver, token = result
        # Attach driver to request for easy access in views
        request.driver = driver
        # Also set request.user to the driver's provider for compatibility
        # with any shared utilities that reference request.user.provider
        request.user = driver.provider
        return driver, token
