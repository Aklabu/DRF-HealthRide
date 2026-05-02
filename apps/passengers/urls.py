from django.urls import path
from .views import (
    PassengerListCreateView,
    PassengerDetailView,
    PassengerOverviewView,
    PassengerMedicalView,
    PassengerHistoryView,
    PassengerOthersView,
)

urlpatterns = [
    # Passenger list and create
    path('', PassengerListCreateView.as_view(), name='passenger-list-create'),

    # Passenger detail and update
    path('<uuid:id>/', PassengerDetailView.as_view(), name='passenger-detail'),

    # Overview — emergency contact + common locations + preferred drivers
    path('<uuid:id>/overview/', PassengerOverviewView.as_view(), name='passenger-overview'),

    # Medical requirements + facility associations
    path('<uuid:id>/medical/', PassengerMedicalView.as_view(), name='passenger-medical'),

    # Trip history + favorite destinations
    path('<uuid:id>/history/', PassengerHistoryView.as_view(), name='passenger-history'),

    # Insurance + payment summary
    path('<uuid:id>/others/', PassengerOthersView.as_view(), name='passenger-others'),
]