from django.urls import path
from .views import (
    CommunicationStatsView,
    ConversationListView,
    ConversationDetailView,
    MessageListView,
    SendMessageView,
    BroadcastView,
)

urlpatterns = [
    # Header stats
    path('', CommunicationStatsView.as_view(), name='communication-stats'),

    # Conversations — list (cursor-paginated) + create
    path('conversations/', ConversationListView.as_view(), name='conversation-list-create'),

    # Conversation detail — metadata only (no messages)
    path('conversations/<uuid:id>/', ConversationDetailView.as_view(), name='conversation-detail'),

    # Messages — paginated list + send
    path('conversations/<uuid:id>/messages/', MessageListView.as_view(), name='message-list'),
    path('conversations/<uuid:id>/messages/send/', SendMessageView.as_view(), name='send-message'),

    # Broadcast — history + send to all drivers
    path('broadcast/', BroadcastView.as_view(), name='broadcast'),
]
