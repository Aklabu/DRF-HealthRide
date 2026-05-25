from django.urls import path
from .views import (
    DriverSigninView, DriverSigninVerifyOTPView,
    DriverForgotPasswordView, DriverForgotPasswordResetView,
    DriverChangePasswordView,
    DriverBasicProfileView, DriverContactProfileView,
    DriverDocumentsView, DriverVehicleUpdateView,
    DriverNotificationPreferencesView, DriverNotificationsView,
    DriverAnnouncementsView, DriverNotificationDeleteView,
    DriverConversationsView, DriverConversationDetailView, DriverSendMessageView,
    DriverVehicleCheckView, DriverDashboardView, DriverScheduleTodayView,
    DriverTripDetailView, DriverTripPickupView, DriverTripStartView,
    DriverTripCompleteView, DriverTripSignatureView, DriverStatusView, DriverLocationView,
)

urlpatterns = [
    # Auth
    path('signin/', DriverSigninView.as_view(), name='driver-signin'),
    path('signin/verify-otp/', DriverSigninVerifyOTPView.as_view(), name='driver-signin-verify-otp'),
    path('forgot-password/', DriverForgotPasswordView.as_view(), name='driver-forgot-password'),
    path('forgot-password/reset/', DriverForgotPasswordResetView.as_view(), name='driver-forgot-password-reset'),
    path('change-password/', DriverChangePasswordView.as_view(), name='driver-change-password'),

    # Profile
    path('profile/basic/', DriverBasicProfileView.as_view(), name='driver-profile-basic'),
    path('profile/contact/', DriverContactProfileView.as_view(), name='driver-profile-contact'),
    path('profile/documents/', DriverDocumentsView.as_view(), name='driver-profile-documents'),
    path('profile/documents/upload/', DriverDocumentsView.as_view(), name='driver-profile-documents-upload'),
    path('profile/vehicle/', DriverVehicleUpdateView.as_view(), name='driver-profile-vehicle'),

    # Notifications
    path('notifications/preferences/', DriverNotificationPreferencesView.as_view(), name='driver-notif-prefs'),
    path('notifications/announcements/', DriverAnnouncementsView.as_view(), name='driver-announcements'),
    path('notifications/<uuid:id>/', DriverNotificationDeleteView.as_view(), name='driver-notif-delete'),
    path('notifications/', DriverNotificationsView.as_view(), name='driver-notifications'),

    # Conversations
    path('conversations/', DriverConversationsView.as_view(), name='driver-conversations'),
    path('conversations/<uuid:id>/', DriverConversationDetailView.as_view(), name='driver-conversation-detail'),
    path('conversations/<uuid:id>/messages/', DriverSendMessageView.as_view(), name='driver-send-message'),

    # Vehicle check
    path('vehicle-check/', DriverVehicleCheckView.as_view(), name='driver-vehicle-check'),

    # Dashboard & schedule
    path('dashboard/', DriverDashboardView.as_view(), name='driver-dashboard'),
    path('schedule/today/', DriverScheduleTodayView.as_view(), name='driver-schedule-today'),

    # Trips
    path('trips/<uuid:id>/', DriverTripDetailView.as_view(), name='driver-trip-detail'),
    path('trips/<uuid:id>/start/', DriverTripStartView.as_view(), name='driver-trip-start'),
    path('trips/<uuid:id>/pickup/', DriverTripPickupView.as_view(), name='driver-trip-pickup'),
    path('trips/<uuid:id>/complete/', DriverTripCompleteView.as_view(), name='driver-trip-complete'),
    path('trips/<uuid:id>/signature/', DriverTripSignatureView.as_view(), name='driver-trip-signature'),

    # Status & location
    path('status/', DriverStatusView.as_view(), name='driver-status'),
    path('location/', DriverLocationView.as_view(), name='driver-location'),
]
