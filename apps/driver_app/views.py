# driver_app views — re-exported from split modules for clean URL imports
from .views_auth import (
    DriverSigninView,
    DriverSigninVerifyOTPView,
    DriverForgotPasswordView,
    DriverForgotPasswordResetView,
    DriverChangePasswordView,
)
from .views_profile import (
    DriverBasicProfileView,
    DriverContactProfileView,
    DriverDocumentsView,
    DriverVehicleUpdateView,
    DriverNotificationPreferencesView,
    DriverNotificationsView,
    DriverAnnouncementsView,
    DriverNotificationDeleteView,
    DriverConversationsView,
    DriverConversationDetailView,
    DriverSendMessageView,
)
from .views_trips import (
    DriverVehicleCheckView,
    DriverDashboardView,
    DriverScheduleTodayView,
    DriverTripDetailView,
    DriverTripPickupView,
    DriverTripStartView,
    DriverTripCompleteView,
    DriverTripSignatureView,
    DriverStatusView,
    DriverLocationView,
)
