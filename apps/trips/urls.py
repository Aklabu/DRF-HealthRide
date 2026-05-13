from django.urls import path
from .views import (
    TripCreateView,
    TripAssignDriverView,
    TripConfirmView,
)

urlpatterns = [
    # Step 1 — Create trip, calculate route & pricing, list available drivers
    path('create', TripCreateView.as_view(), name='trip-create'),

    # Step 2 — Assign driver, store authorization & payment method
    path('<uuid:id>/assign-driver', TripAssignDriverView.as_view(), name='trip-assign-driver'),

    # Step 3 — Confirm or cancel booking, send payment link
    path('<uuid:id>/confirm', TripConfirmView.as_view(), name='trip-confirm'),
]
