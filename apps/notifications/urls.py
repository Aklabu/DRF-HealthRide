from django.urls import path
from .views import (
    NotificationListView,
    NotificationMarkReadView,
    NotificationReadAllView,
    NotificationUnreadCountView,
    NotificationPreferenceView,
    NotificationTemplateListCreateView,
    NotificationTemplateDetailView,
)

urlpatterns = [
    # Inbox
    path('', NotificationListView.as_view(), name='notification-list'),
    path('<uuid:id>/read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('read-all/', NotificationReadAllView.as_view(), name='notification-read-all'),
    path('unread-count/', NotificationUnreadCountView.as_view(), name='notification-unread-count'),

    # Preferences
    path('preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),

    # Templates
    path('templates/', NotificationTemplateListCreateView.as_view(), name='notification-template-list-create'),
    path('templates/<uuid:id>/', NotificationTemplateDetailView.as_view(), name='notification-template-detail'),
]
