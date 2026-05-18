from django.urls import path
from .views import LiveDriversView, LiveTripView

urlpatterns = [
    # All online drivers with current location
    path('drivers/live/', LiveDriversView.as_view(), name='tracking-drivers-live'),

    # Current live state of a specific trip
    path('trips/<uuid:id>/live/', LiveTripView.as_view(), name='tracking-trip-live'),
]
