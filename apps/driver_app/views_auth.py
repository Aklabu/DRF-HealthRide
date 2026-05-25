"""Auth views — signin, OTP verify, forgot password, change password."""
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from utils.response import CustomResponse
from .auth import (
    generate_driver_otp, verify_driver_otp,
    create_session_token, resolve_session_token, invalidate_session_token,
    get_tokens_for_driver,
)
from .permissions import IsDriver
from .serializers import (
    DriverSigninSerializer, DriverOTPVerifySerializer,
    DriverForgotPasswordSerializer, DriverForgotPasswordResetSerializer,
    DriverChangePasswordSerializer,
)


class DriverSigninView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DriverSigninSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        data = serializer.validated_data
        from apps.drivers.models import Driver

        try:
            driver = Driver.objects.get(email=data['email'])
        except Driver.DoesNotExist:
            return CustomResponse.error('Invalid credentials.', 401)

        if driver.status_employment == 'on_leave':
            return CustomResponse.error('Account is deactivated. Contact your provider.', 403)

        if not check_password(data['password'], driver.password):
            return CustomResponse.error('Invalid credentials.', 401)

        otp = generate_driver_otp(driver.id)
        session_token = create_session_token(driver.id, data.get('remember_me', False))

        # Send OTP email async
        try:
            from apps.accounts.emails import send_otp_email
            send_otp_email(driver.email, otp, 'login')
        except Exception:
            pass

        return CustomResponse.success(
            message='OTP sent to registered email.',
            data={'session_token': session_token},
            status_code=200
        )


class DriverSigninVerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DriverOTPVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        data = serializer.validated_data
        session = resolve_session_token(data['session_token'])
        if not session:
            return CustomResponse.error('Session expired. Please sign in again.', 401)

        driver_id = session['driver_id']
        remember_me = session.get('remember_me', False)

        success, error_msg = verify_driver_otp(driver_id, data['otp'])
        if not success:
            if 'Too many' in error_msg:
                invalidate_session_token(data['session_token'])
            return CustomResponse.error(error_msg, 400)

        invalidate_session_token(data['session_token'])

        from apps.drivers.models import Driver
        try:
            driver = Driver.objects.select_related('provider', 'vehicle').get(id=driver_id)
        except Driver.DoesNotExist:
            return CustomResponse.error('Driver not found.', 404)

        tokens = get_tokens_for_driver(driver, remember_me=remember_me)

        vehicle_data = None
        if driver.vehicle:
            vehicle_data = {
                'vehicle_id': str(driver.vehicle.id),
                'vehicle_type': driver.vehicle.vehicle_type,
                'license_plate': driver.vehicle.license_plate,
            }

        return CustomResponse.success(
            message='Login successful.',
            data={
                **tokens,
                'driver': {
                    'id': str(driver.id),
                    'full_name': driver.full_name,
                    'email': driver.email,
                    'phone_number': driver.phone_number,
                    'profile_picture': (
                        request.build_absolute_uri(driver.profile_picture.url)
                        if driver.profile_picture else None
                    ),
                    'status_availability': driver.status_availability,
                    'assigned_vehicle': vehicle_data,
                },
            },
            status_code=200
        )


class DriverForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DriverForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        email = serializer.validated_data['email']
        from apps.drivers.models import Driver

        try:
            driver = Driver.objects.get(email=email)
            otp = generate_driver_otp(driver.id)
            try:
                from apps.accounts.emails import send_otp_email
                send_otp_email(driver.email, otp, 'forgot_password')
            except Exception:
                pass
        except Driver.DoesNotExist:
            pass  # Deliberate — no enumeration

        return CustomResponse.success(
            message='OTP sent if account exists.',
            status_code=200
        )


class DriverForgotPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DriverForgotPasswordResetSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        data = serializer.validated_data
        from apps.drivers.models import Driver

        try:
            driver = Driver.objects.get(email=data['email'])
        except Driver.DoesNotExist:
            return CustomResponse.error('Invalid request.', 400)

        success, error_msg = verify_driver_otp(driver.id, data['otp'])
        if not success:
            return CustomResponse.error(error_msg, 400)

        driver.password = make_password(data['new_password'])
        driver.save(update_fields=['password'])

        return CustomResponse.success(message='Password reset successful.', status_code=200)


class DriverChangePasswordView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def patch(self, request):
        from .auth import DriverJWTAuthentication
        auth = DriverJWTAuthentication()
        result = auth.authenticate(request)
        if not result:
            return CustomResponse.error('Authentication required.', 401)
        driver = request.driver

        serializer = DriverChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        data = serializer.validated_data
        if not check_password(data['current_password'], driver.password):
            return CustomResponse.error('Current password is incorrect.', 400)

        driver.password = make_password(data['new_password'])
        driver.save(update_fields=['password'])

        return CustomResponse.success(message='Password changed successfully.', status_code=200)
