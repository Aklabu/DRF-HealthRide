from django.urls import path
from .views import (
    SchedulingHeaderView,
    ScheduledTripListView,
    ScheduledTripUpdateView,
    UnassignedTripListView,
    AutoAssignView,
)

urlpatterns = [
    # Daily stats header for a specific date
    path('header/', SchedulingHeaderView.as_view(), name='scheduling-header'),

    # Scheduled trip list for a specific date
    path('trips/', ScheduledTripListView.as_view(), name='scheduling-trips'),

    # Update pickup time or driver for a scheduled trip
    path('trips/<uuid:trip_id>/', ScheduledTripUpdateView.as_view(), name='scheduling-trip-update'),

    # Unassigned and driver_absence trip list for a specific date
    path('unassigned/', UnassignedTripListView.as_view(), name='scheduling-unassigned'),

    # Auto-assign drivers to unassigned trips for a specific date
    path('auto-assign/', AutoAssignView.as_view(), name='scheduling-auto-assign'),
]
