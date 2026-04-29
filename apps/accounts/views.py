from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth.hashers import make_password, check_password

from utils.response import CustomResponse
from .models import Provider, ProviderSettings, RateCard
from .serializers import (
    SignupInitiateSerializer,
    SignupVerifyOTPSerializer,
    SignupCompleteSerializer,
    SigninSerializer,
    SigninVerifyOTPSerializer,
    ForgotPasswordSerializer,
    ForgotPasswordVerifyOTPSerializer,
    ForgotPasswordResetSerializer,
    TokenRefreshSerializer,
    LogoutSerializer,
    ProviderProfileSerializer,
    CompanyProfileSerializer,
    ProviderSettingsSerializer,
    RateCardSerializer,
)
from .utils import (
    create_otp,
    verify_otp,
    get_tokens_for_provider,
    generate_reset_token,
    store_reset_token,
    validate_reset_token,
    invalidate_reset_token,
)
from .emails import send_otp_email, send_welcome_email


# Initial signup for create provider and send OTP
class SignupInitiateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupInitiateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Create inactive, unverified provider
        provider = Provider.objects.create(
            business_name=data['business_name'],
            business_email=data['business_email'],
            password=make_password(data['password']),
            is_active=False,
            is_verified=False,
        )

        # Generate OTP and send asynchronously
        otp = create_otp(data['business_email'], 'signup')
        send_otp_email(data['business_email'], otp, 'signup')

        return CustomResponse.success(
            message='OTP sent to your email. Please verify to continue.',
            status_code=200
        )


# Verify OTP for signup
class SignupVerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupVerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        otp_record, error = verify_otp(data['email'], 'signup', data['otp_code'])

        if error:
            return CustomResponse.error(message=error, status_code=400)

        # Mark OTP used and set provider as verified
        otp_record.is_used = True
        otp_record.save()

        try:
            provider = Provider.objects.get(business_email=data['email'], is_active=False)
            provider.is_verified = True
            provider.save()
        except Provider.DoesNotExist:
            return CustomResponse.error(message='Provider not found.', status_code=404)

        return CustomResponse.success(
            message='OTP verified successfully.',
            data={'email': data['email']},
            status_code=200
        )


# Complete signup by adding business info and activating account
class SignupCompleteView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupCompleteSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        try:
            provider = Provider.objects.get(
                business_email=data['email'],
                is_verified=True,
                is_active=False
            )
        except Provider.DoesNotExist:
            return CustomResponse.error(
                message='Verified provider not found. Please complete OTP verification first.',
                status_code=404
            )

        # Save business info
        provider.business_address = data['business_address']
        provider.timezone = data['timezone']
        provider.ein_tax_id = data['ein_tax_id']
        provider.number_of_drivers = data['number_of_drivers']
        provider.number_of_vehicles = data['number_of_vehicles']
        provider.is_active = True
        provider.save()

        # Create default settings and rate card
        ProviderSettings.objects.get_or_create(provider=provider)
        RateCard.objects.get_or_create(provider=provider)

        # Send welcome email
        send_welcome_email(provider.business_email, provider.business_name)

        # Issue tokens
        tokens = get_tokens_for_provider(provider)

        return CustomResponse.success(
            message='Account setup complete. Welcome to Health Ride!',
            data=tokens,
            status_code=201
        )


# Signin with email and password, then send OTP for verification
class SigninView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SigninSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        try:
            provider = Provider.objects.get(business_email=data['email'])
        except Provider.DoesNotExist:
            return CustomResponse.error(message='Invalid credentials.', status_code=401)

        if not provider.is_active:
            return CustomResponse.error(message='Account is not active.', status_code=403)

        if not check_password(data['password'], provider.password):
            return CustomResponse.error(message='Invalid credentials.', status_code=401)

        # Generate OTP and cache remember_me flag
        otp = create_otp(data['email'], 'login')
        send_otp_email(data['email'], otp, 'login')

        # Store remember_me flag in cache tied to this email
        from django.core.cache import cache
        cache.set(f'remember_me_{data["email"]}', data['remember_me'], timeout=600)

        return CustomResponse.success(
            message='OTP sent to your registered email.',
            status_code=200
        )


# Verify OTP for signin and issue tokens
class SigninVerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SigninVerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        otp_record, error = verify_otp(data['email'], 'login', data['otp_code'])

        if error:
            return CustomResponse.error(message=error, status_code=400)

        otp_record.is_used = True
        otp_record.save()

        try:
            provider = Provider.objects.get(business_email=data['email'], is_active=True)
        except Provider.DoesNotExist:
            return CustomResponse.error(message='Provider not found.', status_code=404)

        # Retrieve remember_me flag from cache
        from django.core.cache import cache
        remember_me = cache.get(f'remember_me_{data["email"]}', False)
        cache.delete(f'remember_me_{data["email"]}')

        tokens = get_tokens_for_provider(provider, remember_me=remember_me)
        profile_data = ProviderProfileSerializer(provider).data

        return CustomResponse.success(
            message='Login successful.',
            data={**tokens, 'provider': profile_data},
            status_code=200
        )


# Forgot password — request OTP
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        email = serializer.validated_data['email']

        # Deliberately ambiguous — no enumeration
        try:
            provider = Provider.objects.get(business_email=email, is_active=True)
            otp = create_otp(email, 'forgot_password')
            send_otp_email(email, otp, 'forgot_password')
        except Provider.DoesNotExist:
            pass

        return CustomResponse.success(
            message='If an account exists with this email, an OTP has been sent.',
            status_code=200
        )


# Verify OTP for forgot password and issue reset token
class ForgotPasswordVerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordVerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        otp_record, error = verify_otp(data['email'], 'forgot_password', data['otp_code'])

        if error:
            return CustomResponse.error(message=error, status_code=400)

        otp_record.is_used = True
        otp_record.save()

        # Issue a signed reset token valid for 15 minutes
        reset_token = generate_reset_token()
        store_reset_token(data['email'], reset_token)

        return CustomResponse.success(
            message='OTP verified. Use the reset token to set a new password.',
            data={'reset_token': reset_token},
            status_code=200
        )


# Reset password using the reset token
class ForgotPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordResetSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate reset token
        email = validate_reset_token(data['reset_token'])
        if not email:
            return CustomResponse.error(
                message='Invalid or expired reset token.',
                status_code=400
            )

        try:
            provider = Provider.objects.get(business_email=email, is_active=True)
        except Provider.DoesNotExist:
            return CustomResponse.error(message='Provider not found.', status_code=404)

        # Update password and invalidate token
        provider.password = make_password(data['new_password'])
        provider.save()
        invalidate_reset_token(data['reset_token'])

        return CustomResponse.success(
            message='Password reset successful. Please log in with your new password.',
            status_code=200
        )


# Token refresh endpoint to issue new access token using refresh token
class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        try:
            refresh = RefreshToken(serializer.validated_data['refresh_token'])
            # Verify the provider is still active
            provider_id = refresh.payload.get('user_id')
            provider = Provider.objects.get(id=provider_id, is_active=True)

            # Rotate tokens
            new_refresh = RefreshToken.for_user(provider)
            return CustomResponse.success(
                message='Token refreshed successfully.',
                data={
                    'access_token': str(new_refresh.access_token),
                    'refresh_token': str(new_refresh),
                },
                status_code=200
            )
        except Provider.DoesNotExist:
            return CustomResponse.error(message='Provider account not found or inactive.', status_code=401)
        except TokenError as e:
            return CustomResponse.error(message='Invalid or expired refresh token.', status_code=401)


# Logout by blacklisting the refresh token
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        try:
            refresh = RefreshToken(serializer.validated_data['refresh_token'])
            # Blacklist the refresh token to invalidate session
            refresh.blacklist()
        except TokenError:
            return CustomResponse.error(message='Invalid or already blacklisted token.', status_code=400)

        return CustomResponse.success(message='Logged out successfully.', status_code=200)


# Complete company profile management
class CompanyProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CompanyProfileSerializer(request.user)
        return CustomResponse.success(
            message='Company profile fetched successfully.',
            data=serializer.data,
            status_code=200
        )

    def patch(self, request):
        serializer = CompanyProfileSerializer(
            request.user,
            data=request.data,
            partial=True
        )
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()
        return CustomResponse.success(
            message='Company profile updated successfully.',
            data=serializer.data,
            status_code=200
        )


# Manage platform settings like trip parameters, cancellation policy, and notification preferences
class PlatformSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settings_obj, _ = ProviderSettings.objects.get_or_create(provider=request.user)
        serializer = ProviderSettingsSerializer(settings_obj)

        # Group response into logical sections
        data = serializer.data
        response_data = {
            'trip_parameters': {
                'default_trip_lead_time': data['default_trip_lead_time'],
                'auto_assignment_radius': data['auto_assignment_radius'],
                'enable_auto_assignment': data['enable_auto_assignment'],
            },
            'cancellation_policy': {
                'cancellation_window': data['cancellation_window'],
                'cancellation_fee': data['cancellation_fee'],
            },
            'notification_preferences': {
                'notify_trip_updates': data['notify_trip_updates'],
                'notify_driver_alerts': data['notify_driver_alerts'],
                'notify_passenger_messages': data['notify_passenger_messages'],
                'notify_financial_alerts': data['notify_financial_alerts'],
            }
        }

        return CustomResponse.success(
            message='Platform settings fetched successfully.',
            data=response_data,
            status_code=200
        )

    def patch(self, request):
        settings_obj, _ = ProviderSettings.objects.get_or_create(provider=request.user)
        serializer = ProviderSettingsSerializer(settings_obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()

        # Return same grouped structure
        data = serializer.data
        response_data = {
            'trip_parameters': {
                'default_trip_lead_time': data['default_trip_lead_time'],
                'auto_assignment_radius': data['auto_assignment_radius'],
                'enable_auto_assignment': data['enable_auto_assignment'],
            },
            'cancellation_policy': {
                'cancellation_window': data['cancellation_window'],
                'cancellation_fee': data['cancellation_fee'],
            },
            'notification_preferences': {
                'notify_trip_updates': data['notify_trip_updates'],
                'notify_driver_alerts': data['notify_driver_alerts'],
                'notify_passenger_messages': data['notify_passenger_messages'],
                'notify_financial_alerts': data['notify_financial_alerts'],
            }
        }

        return CustomResponse.success(
            message='Platform settings updated successfully.',
            data=response_data,
            status_code=200
        )


# Manage rate card for different vehicle types
class RateCardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rate_card, _ = RateCard.objects.get_or_create(provider=request.user)
        serializer = RateCardSerializer(rate_card)

        # Group by vehicle type
        data = serializer.data
        response_data = {
            'standard': {
                'base_fare': data['standard_base_fare'],
                'miles_included': data['standard_miles_included'],
                'per_mile_rate': data['standard_per_mile_rate'],
            },
            'wheelchair': {
                'base_fare': data['wheelchair_base_fare'],
                'miles_included': data['wheelchair_miles_included'],
                'per_mile_rate': data['wheelchair_per_mile_rate'],
            },
            'stretcher': {
                'base_fare': data['stretcher_base_fare'],
                'miles_included': data['stretcher_miles_included'],
                'per_mile_rate': data['stretcher_per_mile_rate'],
            }
        }

        return CustomResponse.success(
            message='Rate card fetched successfully.',
            data=response_data,
            status_code=200
        )

    def patch(self, request):
        rate_card, _ = RateCard.objects.get_or_create(provider=request.user)
        serializer = RateCardSerializer(rate_card, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()

        data = serializer.data
        response_data = {
            'standard': {
                'base_fare': data['standard_base_fare'],
                'miles_included': data['standard_miles_included'],
                'per_mile_rate': data['standard_per_mile_rate'],
            },
            'wheelchair': {
                'base_fare': data['wheelchair_base_fare'],
                'miles_included': data['wheelchair_miles_included'],
                'per_mile_rate': data['wheelchair_per_mile_rate'],
            },
            'stretcher': {
                'base_fare': data['stretcher_base_fare'],
                'miles_included': data['stretcher_miles_included'],
                'per_mile_rate': data['stretcher_per_mile_rate'],
            }
        }

        return CustomResponse.success(
            message='Rate card updated successfully.',
            data=response_data,
            status_code=200
        )