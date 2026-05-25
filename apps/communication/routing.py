from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Real-time chat stream for a single conversation
    re_path(
        r'^communication/chat/(?P<conversation_id>[0-9a-f-]+)/$',
        consumers.ChatConsumer.as_asgi(),
    ),

    # Dashboard-level notification stream — unread counts, new conversations, broadcasts
    re_path(
        r'^notifications/$',
        consumers.NotificationConsumer.as_asgi(),
    ),
]
