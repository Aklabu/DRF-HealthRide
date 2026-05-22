from django.urls import path
from .views import (
    TripVolumeReportView,
    DriverHoursReportView,
    PassengerServiceReportView,
    DashboardView,
    ActiveTripsView,
    ComplianceAlertsView,
    DriverStatusView,
)

urlpatterns = [
    # Reports
    path('reports/trip-volume/', TripVolumeReportView.as_view(), name='report-trip-volume'),
    path('reports/driver-hours/', DriverHoursReportView.as_view(), name='report-driver-hours'),
    path('reports/passenger-service/', PassengerServiceReportView.as_view(), name='report-passenger-service'),

    # Dashboard
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('dashboard/active-trips/', ActiveTripsView.as_view(), name='dashboard-active-trips'),
    path('dashboard/compliance-alerts/', ComplianceAlertsView.as_view(), name='dashboard-compliance-alerts'),
    path('dashboard/driver-status/', DriverStatusView.as_view(), name='dashboard-driver-status'),
]
