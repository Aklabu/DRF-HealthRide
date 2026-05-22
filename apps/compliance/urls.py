from django.urls import path
from .views import (
    ComplianceStatsView,
    InspectionListCreateView,
    InspectionDetailView,
    ComplianceDocumentListCreateView,
    ComplianceDocumentDetailView,
    ComplianceAlertListView,
    ComplianceAlertDetailView,
    ComplianceAlertResolveView,
    DocumentSummaryReportView,
    InspectionSummaryReportView,
)

urlpatterns = [
    # Header stats
    path('stats/', ComplianceStatsView.as_view(), name='compliance-stats'),

    # Pre-trip inspections
    path('daily-checkups/', InspectionListCreateView.as_view(), name='inspection-list-create'),
    path('daily-checkups/<uuid:id>/', InspectionDetailView.as_view(), name='inspection-detail'),

    # Compliance documents
    path('documents/', ComplianceDocumentListCreateView.as_view(), name='compliance-doc-list-create'),
    path('documents/<uuid:id>/', ComplianceDocumentDetailView.as_view(), name='compliance-doc-detail'),

    # Compliance alerts
    path('alerts/', ComplianceAlertListView.as_view(), name='compliance-alert-list'),
    path('alerts/<uuid:id>/', ComplianceAlertDetailView.as_view(), name='compliance-alert-detail'),
    path('alerts/<uuid:id>/resolve/', ComplianceAlertResolveView.as_view(), name='compliance-alert-resolve'),

    # Reports
    path('reports/document-summary/', DocumentSummaryReportView.as_view(), name='report-document-summary'),
    path('reports/inspection-summary/', InspectionSummaryReportView.as_view(), name='report-inspection-summary'),
]
