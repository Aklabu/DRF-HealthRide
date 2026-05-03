from django.urls import path
from .views import (
    FacilityListCreateView,
    FacilityDetailView,
    FacilityOverviewView,
    FacilityDetailsView,
    FacilityBillingView,
    FacilityTripsView,
    FacilityDocumentView,
)

urlpatterns = [
    # Facility list and create
    path('', FacilityListCreateView.as_view(), name='facility-list-create'),

    # Facility detail header
    path('<uuid:id>/', FacilityDetailView.as_view(), name='facility-detail'),

    # Overview — contacts + location + performance
    path('<uuid:id>/overview/', FacilityOverviewView.as_view(), name='facility-overview'),

    # Details — contract + pricing + tax
    path('<uuid:id>/details/', FacilityDetailsView.as_view(), name='facility-details'),

    # Billing — invoice list from billing app
    path('<uuid:id>/billing/', FacilityBillingView.as_view(), name='facility-billing'),

    # Trips — trip history from trips app
    path('<uuid:id>/trips/', FacilityTripsView.as_view(), name='facility-trips'),

    # Documents — list and upload
    path('<uuid:id>/documents/', FacilityDocumentView.as_view(), name='facility-documents'),
]