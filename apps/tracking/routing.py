from django.urls import re_path
from . import consumers

# WebSocket URL patterns for the tracking app
websocket_urlpatterns = [
    # Driver app → Server: inbound location stream
    re_path(r'^tracking/driver/(?P<driver_id>[0-9a-f-]+)/$', consumers.DriverLocationConsumer.as_asgi()),

    # Server → Provider: trip progress stream
    re_path(r'^tracking/trip/(?P<trip_id>[0-9a-f-]+)/$', consumers.TripProgressConsumer.as_asgi()),

    # Server → Provider: all-drivers live map
    re_path(r'^tracking/live-map/$', consumers.LiveMapConsumer.as_asgi()),
]
