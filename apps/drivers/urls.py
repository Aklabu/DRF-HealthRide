from django.urls import path
from .views import (
    DriverListCreateView,
    DriverDetailView,
    DriverOverviewView,
    DriverDocumentView,
    DriverAvailabilityView,
    DriverWorkingHoursView,
    DriverEarningsView,
    DriverPayoutView,
)

urlpatterns = [
    # Driver list and create
    path('', DriverListCreateView.as_view(), name='driver-list-create'),

    # Driver detail and update
    path('<uuid:id>/', DriverDetailView.as_view(), name='driver-detail'),

    # Overview — emergency contact + vehicle + certifications
    path('<uuid:id>/overview/', DriverOverviewView.as_view(), name='driver-overview'),

    # Documents
    path('<uuid:id>/documents/', DriverDocumentView.as_view(), name='driver-documents'),

    # Availability schedule
    path('<uuid:id>/availability/', DriverAvailabilityView.as_view(), name='driver-availability'),

    # Working hours breakdown
    path('<uuid:id>/working-hours/', DriverWorkingHoursView.as_view(), name='driver-working-hours'),

    # Earnings summary
    path('<uuid:id>/earnings/', DriverEarningsView.as_view(), name='driver-earnings'),

    # Payouts — preview and create
    path('<uuid:id>/payouts/', DriverPayoutView.as_view(), name='driver-payouts'),
]