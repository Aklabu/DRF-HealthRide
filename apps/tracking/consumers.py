import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


# Resolves a Driver from a JWT token — used by the driver app WebSocket connection
@database_sync_to_async
def get_driver_from_token(token):
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.drivers.models import Driver

        decoded = AccessToken(token)
        # Driver JWTs carry driver_id in the payload, set at login by driver_app
        driver_id = decoded.get('driver_id')
        if not driver_id:
            return None
        return Driver.objects.select_related('provider', 'vehicle').get(id=driver_id)
    except Exception:
        return None


# Resolves a Provider from a JWT token — used by provider-facing WebSocket connections
@database_sync_to_async
def get_provider_from_token(token):
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.accounts.models import Provider

        decoded = AccessToken(token)
        user_id = decoded.get('user_id')
        if not user_id:
            return None
        return Provider.objects.get(id=user_id, is_active=True)
    except Exception:
        return None


# Fetches a trip that belongs to the given provider — prevents cross-provider data access
@database_sync_to_async
def get_trip_for_provider(trip_id, provider):
    try:
        from apps.trips.models import Trip
        return Trip.objects.select_related(
            'driver', 'passenger', 'vehicle'
        ).prefetch_related('passenger_contacts').get(id=trip_id, provider=provider)
    except Exception:
        return None


# Receives inbound GPS frames from the driver mobile app and fans them out to the live map and trip progress groups
# WS: ws://tracking/driver/{driver_id}/
class DriverLocationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        # Parse JWT from the query string — driver app sends ?token=<jwt>
        query_string = self.scope.get('query_string', b'').decode()
        params = dict(p.split('=') for p in query_string.split('&') if '=' in p)
        token = params.get('token', '')

        self.driver = await get_driver_from_token(token)

        # Reject if token is invalid or driver not found
        if not self.driver:
            await self.close(code=4001)
            return

        # Reject if the driver_id in the URL doesn't match the authenticated driver
        url_driver_id = self.scope['url_route']['kwargs'].get('driver_id')
        if str(self.driver.id) != str(url_driver_id):
            await self.close(code=4003)
            return

        self.provider_id = str(self.driver.provider.id)
        self.live_map_group = f'provider.{self.provider_id}.live_map'

        await self.accept()

        # Mark driver online in DB and update availability status
        await self._set_driver_online(True)

        # Join the provider's live map channel group so position broadcasts reach all map viewers
        await self.channel_layer.group_add(self.live_map_group, self.channel_name)

        # Acknowledge successful connection back to the driver app
        await self.send(text_data=json.dumps({
            'type': 'connected',
            'message': 'Location stream active.',
            'driver_id': str(self.driver.id),
        }))

    async def receive(self, text_data):
        try:
            frame = json.loads(text_data)
        except (json.JSONDecodeError, ValueError):
            await self.send(text_data=json.dumps({'type': 'error', 'message': 'Invalid JSON.'}))
            return

        # Only process location_update frames — ignore anything else silently
        if frame.get('type') != 'location_update':
            return

        # Latitude and longitude are required — reject the frame if either is missing
        required = ['latitude', 'longitude']
        for field in required:
            if field not in frame:
                await self.send(text_data=json.dumps({
                    'type': 'error', 'message': f'Missing field: {field}'
                }))
                return

        lat = frame['latitude']
        lng = frame['longitude']
        heading = frame.get('heading')
        speed = frame.get('speed')

        # Persist the latest position to DriverLocation (upsert)
        await self._update_driver_location(lat, lng, heading, speed)

        # Fetch active trip once and reuse it — avoids hitting the DB twice
        active_tracking = await self._get_active_tracking()

        # Queue history write with the trip_id already in hand — no extra DB query needed
        trip_id = str(active_tracking.trip_id) if active_tracking else None
        await self._queue_history_write(lat, lng, trip_id)

        if active_tracking:
            # Update the live coordinates on the active trip tracking record
            await self._update_active_tracking(active_tracking, lat, lng)

            # Kick off async ETA recalculation via Google Maps
            await self._queue_eta_recompute(active_tracking.id, lat, lng)

            # Push location update to the provider watching this specific trip
            trip_group = f'trip.{active_tracking.trip_id}.progress'
            await self.channel_layer.group_send(trip_group, {
                'type': 'trip_update',
                'current_location': {'latitude': lat, 'longitude': lng},
                'eta_minutes': active_tracking.eta_minutes,
                'tracking_status': active_tracking.status,
                'last_updated': timezone.now().isoformat(),
            })

        # Push driver position to all provider dashboard map viewers
        await self.channel_layer.group_send(self.live_map_group, {
            'type': 'driver_position',
            'driver_id': str(self.driver.id),
            'full_name': self.driver.full_name,
            'latitude': lat,
            'longitude': lng,
            'heading': heading,
            'speed': speed,
            'status_availability': self.driver.status_availability,
            'vehicle_type': self.driver.vehicle.vehicle_type if self.driver.vehicle else None,
            'timestamp': timezone.now().isoformat(),
        })

    async def disconnect(self, close_code):
        if hasattr(self, 'driver') and self.driver:
            # Mark driver offline in DB and update availability status
            await self._set_driver_online(False)

            if hasattr(self, 'live_map_group'):
                # Notify map viewers that this driver has gone offline
                await self.channel_layer.group_send(self.live_map_group, {
                    'type': 'driver_offline',
                    'driver_id': str(self.driver.id),
                })
                await self.channel_layer.group_discard(self.live_map_group, self.channel_name)

    # Upserts DriverLocation.is_online and syncs Driver.status_availability accordingly
    @database_sync_to_async
    def _set_driver_online(self, is_online):
        from .models import DriverLocation
        from apps.drivers.models import Driver

        DriverLocation.objects.update_or_create(
            driver=self.driver,
            defaults={
                'provider': self.driver.provider,
                'latitude': 0,
                'longitude': 0,
                'is_online': is_online,
            }
        )

        if is_online:
            # Only move to available if the driver was off_duty — don't override on_trip
            Driver.objects.filter(
                id=self.driver.id,
                status_availability='off_duty',
            ).update(status_availability='available')
        else:
            # Only move to off_duty if the driver isn't currently on an active trip
            Driver.objects.filter(
                id=self.driver.id,
            ).exclude(
                status_availability='on_trip',
            ).update(status_availability='off_duty')

    # Upserts the driver's current lat/lng, heading, and speed into DriverLocation
    @database_sync_to_async
    def _update_driver_location(self, lat, lng, heading, speed):
        from .models import DriverLocation
        DriverLocation.objects.update_or_create(
            driver=self.driver,
            defaults={
                'provider': self.driver.provider,
                'latitude': lat,
                'longitude': lng,
                'heading': heading,
                'speed': speed,
                'is_online': True,
            }
        )

    # Dispatches a Celery task to persist this location point to DriverLocationHistory
    @database_sync_to_async
    def _queue_history_write(self, lat, lng, trip_id):
        try:
            from .tasks import write_location_history
            write_location_history.delay(
                str(self.driver.id), lat, lng,
                timezone.now().isoformat(), trip_id
            )
        except Exception:
            # Celery unavailable — skip silently, history loss is acceptable
            pass

    # Returns the driver's current ActiveTripTracking record, or None if not on a trip
    @database_sync_to_async
    def _get_active_tracking(self):
        from .models import ActiveTripTracking
        try:
            return ActiveTripTracking.objects.get(driver=self.driver)
        except ActiveTripTracking.DoesNotExist:
            return None

    # Updates the live coordinates on the active trip tracking record
    @database_sync_to_async
    def _update_active_tracking(self, tracking, lat, lng):
        from .models import ActiveTripTracking
        ActiveTripTracking.objects.filter(id=tracking.id).update(
            current_lat=lat,
            current_lng=lng,
        )

    # Dispatches a Celery task to recalculate ETA via Google Maps and broadcast the result
    @database_sync_to_async
    def _queue_eta_recompute(self, tracking_id, lat, lng):
        try:
            from .tasks import recompute_eta
            recompute_eta.delay(str(tracking_id), lat, lng)
        except Exception:
            pass

    # Forwards driver_position channel layer messages to this WebSocket connection
    async def driver_position(self, event):
        await self.send(text_data=json.dumps(event))

    # Forwards driver_offline channel layer messages to this WebSocket connection
    async def driver_offline(self, event):
        await self.send(text_data=json.dumps(event))


# Streams live trip progress updates to a provider watching a specific trip
# WS: ws://tracking/trip/{trip_id}/
class TripProgressConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        query_string = self.scope.get('query_string', b'').decode()
        params = dict(p.split('=') for p in query_string.split('&') if '=' in p)
        token = params.get('token', '')

        self.provider = await get_provider_from_token(token)
        if not self.provider:
            await self.close(code=4001)
            return

        trip_id = self.scope['url_route']['kwargs'].get('trip_id')
        self.trip = await get_trip_for_provider(trip_id, self.provider)

        # Reject if trip doesn't exist or belongs to a different provider
        if not self.trip:
            await self.close(code=4004)
            return

        # Only accept connections while the trip is actively moving
        # on_way = driver heading to pickup, in_progress = passenger onboard, awaiting_signature = at dropoff
        if self.trip.status not in ('on_way', 'in_progress', 'awaiting_signature'):
            await self.close(code=4000)
            return

        self.trip_group = f'trip.{trip_id}.progress'
        await self.accept()
        await self.channel_layer.group_add(self.trip_group, self.channel_name)

        # Send the current state immediately so the client doesn't wait for the next location frame
        snapshot = await self._get_trip_snapshot()
        await self.send(text_data=json.dumps(snapshot))

    async def disconnect(self, close_code):
        if hasattr(self, 'trip_group'):
            await self.channel_layer.group_discard(self.trip_group, self.channel_name)

    # Forwards live location and ETA updates pushed by DriverLocationConsumer
    async def trip_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'trip_update',
            'current_location': event.get('current_location'),
            'eta_minutes': event.get('eta_minutes'),
            'tracking_status': event.get('tracking_status'),
            'last_updated': event.get('last_updated'),
        }))

    # Forwards trip status transitions pushed by driver_app views (e.g. pickup confirmed, arrived at dropoff)
    async def status_change(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_change',
            'new_status': event.get('new_status'),
            'tracking_status': event.get('tracking_status'),
            'changed_at': event.get('changed_at'),
            'message': event.get('message', ''),
        }))

    # Notifies the client that the trip is complete, then closes the connection
    async def trip_completed(self, event):
        await self.send(text_data=json.dumps({
            'type': 'trip_completed',
            'completed_at': event.get('completed_at'),
            'trip_id': event.get('trip_id'),
        }))
        await self.close()

    # Builds the initial state snapshot sent on connect — includes current location, ETA, and tracking status
    @database_sync_to_async
    def _get_trip_snapshot(self):
        from .models import ActiveTripTracking
        try:
            tracking = ActiveTripTracking.objects.get(trip=self.trip)
            return {
                'type': 'initial_snapshot',
                'trip_id': str(self.trip.id),
                'status': self.trip.status,
                'current_location': {
                    'latitude': float(tracking.current_lat),
                    'longitude': float(tracking.current_lng),
                    'last_updated': tracking.last_updated.isoformat(),
                },
                'eta_minutes': tracking.eta_minutes,
                'tracking_status': tracking.status,
                'started_at': self.trip.started_at.isoformat() if self.trip.started_at else None,
            }
        except ActiveTripTracking.DoesNotExist:
            # Trip started but tracking record not yet created — return nulls
            return {
                'type': 'initial_snapshot',
                'trip_id': str(self.trip.id),
                'status': self.trip.status,
                'current_location': None,
                'eta_minutes': None,
                'tracking_status': None,
                'started_at': self.trip.started_at.isoformat() if self.trip.started_at else None,
            }


# Streams all online driver positions to a provider's fleet map dashboard
# WS: ws://tracking/live-map/
class LiveMapConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        query_string = self.scope.get('query_string', b'').decode()
        params = dict(p.split('=') for p in query_string.split('&') if '=' in p)
        token = params.get('token', '')

        self.provider = await get_provider_from_token(token)
        if not self.provider:
            await self.close(code=4001)
            return

        # Each provider has its own isolated live map channel group
        self.live_map_group = f'provider.{self.provider.id}.live_map'
        await self.accept()
        await self.channel_layer.group_add(self.live_map_group, self.channel_name)

        # Send all currently online drivers immediately so the map populates without waiting for movement
        snapshot = await self._get_online_drivers_snapshot()
        await self.send(text_data=json.dumps({
            'type': 'initial_snapshot',
            'online_drivers': snapshot,
            'total_online': len(snapshot),
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'live_map_group'):
            await self.channel_layer.group_discard(self.live_map_group, self.channel_name)

    # Forwards a driver's updated position to all connected map viewers for this provider
    async def driver_position(self, event):
        await self.send(text_data=json.dumps({
            'type': 'driver_position',
            'driver_id': event.get('driver_id'),
            'full_name': event.get('full_name'),
            'latitude': event.get('latitude'),
            'longitude': event.get('longitude'),
            'heading': event.get('heading'),
            'speed': event.get('speed'),
            'status_availability': event.get('status_availability'),
            'vehicle_type': event.get('vehicle_type'),
            'timestamp': event.get('timestamp'),
        }))

    # Notifies map viewers that a driver has disconnected and should be removed from the map
    async def driver_offline(self, event):
        await self.send(text_data=json.dumps({
            'type': 'driver_offline',
            'driver_id': event.get('driver_id'),
        }))

    # Queries all currently online drivers for this provider and returns their positions
    @database_sync_to_async
    def _get_online_drivers_snapshot(self):
        from .models import DriverLocation
        locations = DriverLocation.objects.filter(
            provider=self.provider,
            is_online=True,
        ).select_related('driver', 'driver__vehicle')

        result = []
        for loc in locations:
            result.append({
                'driver_id': str(loc.driver.id),
                'full_name': loc.driver.full_name,
                'latitude': float(loc.latitude),
                'longitude': float(loc.longitude),
                'heading': float(loc.heading) if loc.heading else None,
                'speed': float(loc.speed) if loc.speed else None,
                'status_availability': loc.driver.status_availability,
                'vehicle_type': loc.driver.vehicle.vehicle_type if loc.driver.vehicle else None,
                'timestamp': loc.timestamp.isoformat(),
            })
        return result
