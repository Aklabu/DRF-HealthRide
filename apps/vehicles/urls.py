from django.urls import path
from .views import (
    VehicleListCreateView,
    VehicleDetailView,
    VehicleSpecificationsView,
    VehicleMaintenanceView,
    VehicleDocumentView,
    VehicleAssignDriverView,
)

urlpatterns = [
    # Vehicle list and create
    path('', VehicleListCreateView.as_view(), name='vehicle-list-create'),

    # Vehicle detail and update
    path('<uuid:id>/', VehicleDetailView.as_view(), name='vehicle-detail'),

    # Vehicle specifications
    path('<uuid:id>/specifications/', VehicleSpecificationsView.as_view(), name='vehicle-specifications'),

    # Maintenance records
    path('<uuid:id>/maintenance/', VehicleMaintenanceView.as_view(), name='vehicle-maintenance'),

    # Documents
    path('<uuid:id>/documents/', VehicleDocumentView.as_view(), name='vehicle-documents'),

    # Assign driver
    path('<uuid:id>/assign-driver/', VehicleAssignDriverView.as_view(), name='vehicle-assign-driver'),
]