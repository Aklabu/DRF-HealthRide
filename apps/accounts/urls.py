from django.urls import path
from .views import (
    SignupInitiateView,
    SignupVerifyOTPView,
    SignupCompleteView,
    SigninView,
    SigninVerifyOTPView,
    ForgotPasswordView,
    ForgotPasswordVerifyOTPView,
    ForgotPasswordResetView,
    TokenRefreshView,
    LogoutView,
    CompanyProfileView,
    PlatformSettingsView,
    RateCardView,
)

urlpatterns = [
    # Signup flow
    path('signup/initiate/', SignupInitiateView.as_view(), name='signup-initiate'),
    path('signup/verify-otp/', SignupVerifyOTPView.as_view(), name='signup-verify-otp'),
    path('signup/complete/', SignupCompleteView.as_view(), name='signup-complete'),

    # Signin flow
    path('signin/', SigninView.as_view(), name='signin'),
    path('signin/verify-otp/', SigninVerifyOTPView.as_view(), name='signin-verify-otp'),

    # Forgot password flow
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('forgot-password/verify-otp/', ForgotPasswordVerifyOTPView.as_view(), name='forgot-password-verify-otp'),
    path('forgot-password/reset/', ForgotPasswordResetView.as_view(), name='forgot-password-reset'),

    # Token management
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Settings
    path('settings/company-profile/', CompanyProfileView.as_view(), name='company-profile'),
    path('settings/platform/', PlatformSettingsView.as_view(), name='platform-settings'),
    path('settings/rates/', RateCardView.as_view(), name='rate-card'),
]