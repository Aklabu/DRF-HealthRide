from django.urls import path
from .views import (
    TripListCreateView,
    TripDetailView,
    TripStatusUpdateView,
    TripAssignDriverView,
    TripSignatureView,
    CalculateRouteView,
    CalculatePricingView,
)

urlpatterns = [
    # Trip list and create
    path('', TripListCreateView.as_view(), name='trip-list-create'),

    # Stateless route calculation
    path('calculate-route/', CalculateRouteView.as_view(), name='trip-calculate-route'),

    # Stateless pricing calculation
    path('calculate-pricing/', CalculatePricingView.as_view(), name='trip-calculate-pricing'),

    # Trip detail
    path('<uuid:id>/', TripDetailView.as_view(), name='trip-detail'),

    # Status update
    path('<uuid:id>/status/', TripStatusUpdateView.as_view(), name='trip-status-update'),

    # Manual driver assignment
    path('<uuid:id>/assign-driver/', TripAssignDriverView.as_view(), name='trip-assign-driver'),

    # Signature submission
    path('<uuid:id>/signature/', TripSignatureView.as_view(), name='trip-signature'),
]