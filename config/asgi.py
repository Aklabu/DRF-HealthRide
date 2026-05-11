"""
ASGI config for HealthRide.

Handles both HTTP (via Django) and WebSocket (via Django Channels) connections.
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django ASGI app early to populate app registry before importing consumers
django_asgi_app = get_asgi_application()

from apps.tracking.routing import websocket_urlpatterns as tracking_ws  # noqa: E402
from apps.communication.routing import websocket_urlpatterns as communication_ws  # noqa: E402

websocket_urlpatterns = tracking_ws + communication_ws

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        URLRouter(websocket_urlpatterns)
    ),
})
