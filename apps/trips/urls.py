from django.urls import path
from .views import (
    TripCreateView,
    TripAssignDriverView,
    TripConfirmView,
    TripListView,
    TripCancelView,
)

urlpatterns = [
    # Create trip, calculate route & pricing, list available drivers
    path('create', TripCreateView.as_view(), name='trip-create'),

    # Assign driver, store authorization & payment method
    path('<uuid:id>/assign-driver', TripAssignDriverView.as_view(), name='trip-assign-driver'),

    # Confirm or cancel booking, send payment link
    path('<uuid:id>/confirm', TripConfirmView.as_view(), name='trip-confirm'),
    
    # Retrieve list of all trips with statistics
    path('list', TripListView.as_view(), name='trip-list'),
    
    # Cancel a trip at any stage
    path('<uuid:id>/cancel', TripCancelView.as_view(), name='trip-cancel'),
]