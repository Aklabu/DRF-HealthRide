# Celery tasks for the tracking app — run asynchronously so they never block the real-time WebSocket path
from django.utils import timezone


# Persists a single GPS point to DriverLocationHistory — called on every location frame received from the driver app
def write_location_history(driver_id, latitude, longitude, timestamp_iso, trip_id=None):
    try:
        from .models import DriverLocationHistory
        from apps.drivers.models import Driver
        from datetime import datetime

        driver = Driver.objects.get(id=driver_id)

        # Link the history point to the active trip if the driver is currently on one
        trip = None
        if trip_id:
            from apps.trips.models import Trip
            try:
                trip = Trip.objects.get(id=trip_id)
            except Trip.DoesNotExist:
                pass

        ts = datetime.fromisoformat(timestamp_iso)
        if timezone.is_naive(ts):
            ts = timezone.make_aware(ts)

        DriverLocationHistory.objects.create(
            driver=driver,
            latitude=latitude,
            longitude=longitude,
            timestamp=ts,
            trip=trip,
        )
    except Exception:
        # Never raise — a history write failure must not affect the real-time path
        pass


# Recalculates ETA to the dropoff location using Google Maps Distance Matrix API and broadcasts the result
def recompute_eta(tracking_id, current_lat, current_lng):
    try:
        from .models import ActiveTripTracking
        import requests
        from django.conf import settings
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        tracking = ActiveTripTracking.objects.select_related('trip').get(id=tracking_id)
        trip = tracking.trip

        # Use stored coordinates when available — more reliable than geocoding an address string each time
        if trip.dropoff_latitude and trip.dropoff_longitude:
            destination = f'{trip.dropoff_latitude},{trip.dropoff_longitude}'
        else:
            destination = trip.dropoff_address

        api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
        if not api_key:
            return

        url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
        params = {
            'origins': f'{current_lat},{current_lng}',
            'destinations': destination,
            'units': 'imperial',
            'key': api_key,
        }

        response = requests.get(url, params=params, timeout=8)
        data = response.json()

        if data.get('status') != 'OK':
            return

        element = data['rows'][0]['elements'][0]
        if element.get('status') != 'OK':
            return

        duration_seconds = element['duration']['value']
        eta_minutes = round(duration_seconds / 60)

        # Persist the new ETA to the tracking record
        ActiveTripTracking.objects.filter(id=tracking_id).update(eta_minutes=eta_minutes)

        # Push the updated ETA to the provider watching this trip via WebSocket
        channel_layer = get_channel_layer()
        trip_group = f'trip.{tracking.trip_id}.progress'
        async_to_sync(channel_layer.group_send)(trip_group, {
            'type': 'trip_update',
            'current_location': {
                'latitude': current_lat,
                'longitude': current_lng,
            },
            'eta_minutes': eta_minutes,
            'tracking_status': tracking.status,
            'last_updated': timezone.now().isoformat(),
        })

    except Exception:
        pass


# Register both functions as Celery tasks when Celery is available
# They remain plain callables when Celery is not configured — .delay() calls fail silently
try:
    from config.celery import app as celery_app

    write_location_history = celery_app.task(
        name='tracking.write_location_history',
        ignore_result=True,
        bind=False,
    )(write_location_history)

    recompute_eta = celery_app.task(
        name='tracking.recompute_eta',
        ignore_result=True,
        bind=False,
    )(recompute_eta)

except Exception:
    pass
