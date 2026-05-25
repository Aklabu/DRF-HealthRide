"""Trip, dashboard, status, location, vehicle-check views."""
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.utils import timezone
from django.shortcuts import get_object_or_404
from decimal import Decimal

from utils.response import CustomResponse
from .auth import DriverJWTAuthentication
from .permissions import IsDriver
from .serializers import (
    DriverStatusUpdateSerializer,
    DriverLocationUpdateSerializer,
    TripSignatureUploadSerializer,
)


def _passenger_info(trip, request):
    if trip.passenger:
        return {
            'name': trip.passenger.full_name,
            'phone': trip.passenger.phone_number,
            'image': (
                request.build_absolute_uri(trip.passenger.profile_picture.url)
                if trip.passenger.profile_picture else None
            ),
        }
    contact = trip.passenger_contacts.first()
    if contact:
        return {'name': contact.full_name, 'phone': contact.phone_number, 'image': None}
    return None


class DriverVehicleCheckView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        driver = request.driver
        if not driver.vehicle:
            return CustomResponse.error(
                'No vehicle assigned. Please assign a vehicle before submitting an inspection.',
                400
            )

        # Inject driver and vehicle into request data
        data = request.data.copy()
        data['driver'] = str(driver.id)
        data['vehicle'] = str(driver.vehicle.id)

        # Proxy to compliance app
        from apps.compliance.serializers import InspectionCreateSerializer
        from apps.compliance.models import PreTripInspection, InspectionSchedule, ComplianceAlert
        from apps.compliance.utils import invalidate_stats_cache

        serializer = InspectionCreateSerializer(data=data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        d = serializer.validated_data
        checklist_fields = [
            'vehicle_exterior', 'vehicle_interior', 'tires', 'brakes',
            'fluids', 'lights', 'safety_equipment', 'cleanliness',
            'dashboard_warning_lights',
        ]
        has_failure = any(d.get(f) == 'fail' for f in checklist_fields)
        if d.get('wheelchair_ramp') == 'fail':
            has_failure = True
        status = 'issues_found' if has_failure else 'all_clear'

        from django.db import transaction
        with transaction.atomic():
            inspection = PreTripInspection.objects.create(
                provider=driver.provider,
                driver=driver,
                vehicle=driver.vehicle,
                date_time=timezone.now(),
                odometer=d['odometer'],
                fuel_level=d['fuel_level'],
                status=status,
                vehicle_exterior=d['vehicle_exterior'],
                vehicle_interior=d['vehicle_interior'],
                tires=d['tires'],
                brakes=d['brakes'],
                fluids=d['fluids'],
                lights=d['lights'],
                safety_equipment=d['safety_equipment'],
                cleanliness=d['cleanliness'],
                wheelchair_ramp=d.get('wheelchair_ramp', 'not_applicable'),
                dashboard_warning_lights=d['dashboard_warning_lights'],
                issue_description=d.get('issue_description'),
                issue_photo=d.get('issue_photo'),
                signature=d['signature'],
            )

            today = timezone.now().date()
            try:
                schedule = InspectionSchedule.objects.get(
                    provider=driver.provider,
                    driver=driver,
                    vehicle=driver.vehicle,
                    expected_date=today,
                )
                schedule.inspection_submitted = True
                schedule.inspection = inspection
                schedule.save(update_fields=['inspection_submitted', 'inspection'])
            except InspectionSchedule.DoesNotExist:
                pass

            if status == 'issues_found':
                severity = 'critical' if inspection.has_critical_failure() else 'warning'
                ComplianceAlert.objects.create(
                    provider=driver.provider,
                    alert_type='inspection_failed',
                    severity=severity,
                    title=f'Pre-Trip Inspection Failed — {driver.full_name}',
                    description=f'Issues reported on vehicle {driver.vehicle.license_plate}.',
                    holder_type='driver',
                    holder_id=driver.id,
                    holder_name=driver.full_name,
                    related_inspection=inspection,
                    due_date=today,
                )

        invalidate_stats_cache(str(driver.provider.id))

        return CustomResponse.success(
            message='Inspection submitted.',
            data={'inspection_id': str(inspection.id), 'status': inspection.status},
            status_code=201
        )


class DriverDashboardView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        from apps.trips.models import Trip
        from apps.drivers.models import DriverWorkLog
        from django.db.models import Sum

        driver = request.driver
        today = timezone.now().date()

        total_today = Trip.objects.filter(driver=driver, pickup_date=today).count()
        completed_today = Trip.objects.filter(
            driver=driver, status='completed', completed_at__date=today
        ).count()

        hours_today = DriverWorkLog.objects.filter(
            driver=driver, date=today
        ).aggregate(h=Sum('hours_worked'))['h'] or Decimal('0.00')

        total_miles = Trip.objects.filter(
            driver=driver, status='completed', completed_at__date=today
        ).aggregate(m=Sum('estimated_distance'))['m'] or Decimal('0.00')

        schedule_qs = Trip.objects.filter(
            driver=driver,
            pickup_date=today,
        ).exclude(status='cancelled').select_related(
            'passenger', 'vehicle'
        ).prefetch_related('passenger_contacts').order_by('pickup_time')[:5]

        schedule = []
        for trip in schedule_qs:
            pax = _passenger_info(trip, request)
            schedule.append({
                'trip_id': str(trip.id),
                'passenger_name': pax['name'] if pax else None,
                'passenger_image': pax['image'] if pax else None,
                'scheduled_time': trip.pickup_time,
                'pickup_location': trip.pickup_address,
                'dropoff_location': trip.dropoff_address,
                'distance_miles': trip.estimated_distance,
                'estimated_duration_minutes': trip.estimated_duration,
            })

        return CustomResponse.success(
            message='Dashboard fetched.',
            data={
                'daily_stats': {
                    'total_trips_today': total_today,
                    'completed_today': completed_today,
                    'hours_online_today': str(hours_today),
                    'total_miles_today': str(total_miles),
                },
                'operational_status': driver.status_availability,
                'todays_schedule': schedule,
            },
            status_code=200
        )


class DriverScheduleTodayView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        from apps.trips.models import Trip

        today = timezone.now().date()
        trips = Trip.objects.filter(
            driver=request.driver,
            pickup_date=today,
        ).exclude(status='cancelled').select_related(
            'passenger', 'vehicle'
        ).prefetch_related('passenger_contacts').order_by('pickup_time')

        results = []
        for trip in trips:
            pax = _passenger_info(trip, request)
            results.append({
                'trip_id': str(trip.id),
                'passenger_name': pax['name'] if pax else None,
                'passenger_image': pax['image'] if pax else None,
                'scheduled_time': trip.pickup_time,
                'pickup_location': trip.pickup_address,
                'dropoff_location': trip.dropoff_address,
                'distance_miles': trip.estimated_distance,
                'estimated_duration_minutes': trip.estimated_duration,
                'trip_status': trip.status,
            })

        return CustomResponse.success(
            message='Today\'s schedule fetched.',
            data={'results': results},
            status_code=200
        )


class DriverTripDetailView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request, id):
        from apps.trips.models import Trip

        trip = get_object_or_404(Trip, id=id, driver=request.driver)
        pax = _passenger_info(trip, request)
        today = timezone.now().date()

        return CustomResponse.success(
            message='Trip fetched.',
            data={
                'trip_id': str(trip.id),
                'scheduled_time': trip.pickup_time,
                'passenger_name': pax['name'] if pax else None,
                'passenger_image': pax['image'] if pax else None,
                'passenger_phone': pax['phone'] if pax else None,
                'pickup_location': trip.pickup_address,
                'dropoff_location': trip.dropoff_address,
                'distance_miles': trip.estimated_distance,
                'estimated_duration_minutes': trip.estimated_duration,
                'special_requirements': trip.special_requirements,
                'trip_status': trip.status,
                'start_trip_available': (
                    trip.status == 'scheduled' and trip.pickup_date == today
                ),
                'confirm_pickup_available': trip.status == 'on_way',
                'signature_available': trip.status == 'in_progress',
                'complete_available': trip.status == 'awaiting_signature',
            },
            status_code=200
        )


class DriverTripPickupView(APIView):
    """
    Driver confirms passenger has been picked up.
    Transitions trip to in_progress and tracking status to passenger_onboard.
    """
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def patch(self, request, id):
        from apps.trips.models import Trip, TripStatusLog

        trip = get_object_or_404(Trip, id=id, driver=request.driver)

        if trip.status != 'on_way':
            return CustomResponse.error(
                f'Passenger pickup cannot be confirmed — current status is "{trip.status}".', 400
            )

        now = timezone.now()
        trip.status = 'in_progress'
        trip.save(update_fields=['status'])

        TripStatusLog.objects.create(
            trip=trip, from_status='on_way', to_status='in_progress',
            changed_by='driver', notes='Driver confirmed passenger onboard.'
        )

        # Update ActiveTripTracking status to passenger_onboard
        try:
            from apps.tracking.models import ActiveTripTracking
            ActiveTripTracking.objects.filter(trip=trip).update(status='passenger_onboard')
        except Exception:
            pass

        # Broadcast status change to any connected TripProgressConsumer
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'trip.{trip.id}.progress',
                {
                    'type': 'status_change',
                    'new_status': 'in_progress',
                    'tracking_status': 'passenger_onboard',
                    'changed_at': now.isoformat(),
                    'message': 'Passenger is onboard.',
                }
            )
        except Exception:
            pass

        return CustomResponse.success(
            message='Passenger onboard confirmed.',
            data={'trip_id': str(trip.id), 'status': trip.status},
            status_code=200
        )


class DriverTripStartView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def patch(self, request, id):
        from apps.trips.models import Trip, TripStatusLog
        from apps.tracking.models import ActiveTripTracking

        trip = get_object_or_404(Trip, id=id, driver=request.driver)
        today = timezone.now().date()

        if trip.status != 'scheduled':
            return CustomResponse.error(
                f'Trip cannot be started — current status is "{trip.status}".', 400
            )
        if trip.pickup_date != today:
            return CustomResponse.error('Cannot start a trip scheduled for a future date.', 400)

        now = timezone.now()
        trip.status = 'on_way'
        trip.started_at = now
        trip.save(update_fields=['status', 'started_at'])

        # Mark driver as on_trip
        request.driver.status_availability = 'on_trip'
        request.driver.save(update_fields=['status_availability'])

        TripStatusLog.objects.create(
            trip=trip, from_status='scheduled', to_status='on_way',
            changed_by='driver', notes='Driver started trip.'
        )

        # Create ActiveTripTracking record seeded with driver's last known position
        try:
            from apps.tracking.models import DriverLocation
            loc = DriverLocation.objects.get(driver=request.driver)
            lat = loc.latitude
            lng = loc.longitude
        except Exception:
            lat, lng = Decimal('0.000000'), Decimal('0.000000')

        ActiveTripTracking.objects.get_or_create(
            trip=trip,
            defaults={
                'driver': request.driver,
                'provider': request.driver.provider,
                'current_lat': lat,
                'current_lng': lng,
                'status': 'en_route_to_pickup',
            }
        )

        # Broadcast status change to any connected TripProgressConsumer
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'trip.{trip.id}.progress',
                {
                    'type': 'status_change',
                    'new_status': 'on_way',
                    'tracking_status': 'en_route_to_pickup',
                    'changed_at': now.isoformat(),
                    'message': 'Driver is on the way.',
                }
            )
        except Exception:
            pass

        # Build Google Maps URL
        maps_url = (
            f'https://www.google.com/maps/dir/?api=1'
            f'&origin={lat},{lng}'
            f'&destination={trip.pickup_address}'
            f'&waypoints={trip.dropoff_address}'
        )

        return CustomResponse.success(
            message='Trip started.',
            data={
                'trip_id': str(trip.id),
                'status': trip.status,
                'navigation': {
                    'origin': f'{lat},{lng}',
                    'pickup_location': trip.pickup_address,
                    'dropoff_location': trip.dropoff_address,
                    'google_maps_url': maps_url,
                },
            },
            status_code=200
        )


class DriverTripCompleteView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def patch(self, request, id):
        from apps.trips.models import Trip, TripSignature, TripStatusLog
        from apps.drivers.models import DriverWorkLog
        from apps.trips.utils import handle_trip_completion

        trip = get_object_or_404(Trip, id=id, driver=request.driver)

        if trip.status not in ('on_way', 'in_progress', 'awaiting_signature'):
            return CustomResponse.error(
                f'Trip cannot be completed — current status is "{trip.status}".', 400
            )

        # Signature must exist
        try:
            trip.signature
        except TripSignature.DoesNotExist:
            return CustomResponse.error(
                'Passenger signature must be submitted before completing the trip.', 400
            )

        now = timezone.now()
        old_status = trip.status
        trip.status = 'completed'
        trip.completed_at = now
        trip.save(update_fields=['status', 'completed_at'])

        request.driver.status_availability = 'available'
        request.driver.save(update_fields=['status_availability'])

        TripStatusLog.objects.create(
            trip=trip, from_status=old_status, to_status='completed',
            changed_by='driver', notes='Driver completed trip.'
        )

        # Delete ActiveTripTracking
        try:
            from apps.tracking.models import ActiveTripTracking
            ActiveTripTracking.objects.filter(trip=trip).delete()
        except Exception:
            pass

        # Broadcast trip_completed to any connected TripProgressConsumer
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'trip.{trip.id}.progress',
                {
                    'type': 'trip_completed',
                    'trip_id': str(trip.id),
                    'completed_at': now.isoformat(),
                }
            )
        except Exception:
            pass

        handle_trip_completion(trip)

        return CustomResponse.success(
            message='Trip completed.',
            data={'trip_id': str(trip.id), 'status': 'completed', 'completed_at': now},
            status_code=200
        )


class DriverTripSignatureView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, id):
        from apps.trips.models import Trip, TripSignature

        trip = get_object_or_404(Trip, id=id, driver=request.driver)

        if trip.status not in ('on_way', 'in_progress', 'awaiting_signature'):
            return CustomResponse.error(
                f'Signature cannot be submitted — trip status is "{trip.status}".', 400
            )

        if TripSignature.objects.filter(trip=trip).exists():
            return CustomResponse.error('Signature already submitted for this trip.', 400)

        serializer = TripSignatureUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        now = timezone.now()
        sig = TripSignature.objects.create(
            trip=trip,
            signature_image=serializer.validated_data['signature'],
            signed_at=now,
            confirmed_by_driver=True,
        )

        # Advance trip to awaiting_signature and update tracking status
        old_status = trip.status
        if trip.status != 'awaiting_signature':
            trip.status = 'awaiting_signature'
            trip.save(update_fields=['status'])

        # Update ActiveTripTracking status to arrived_at_dropoff
        try:
            from apps.tracking.models import ActiveTripTracking
            ActiveTripTracking.objects.filter(trip=trip).update(status='arrived_at_dropoff')
        except Exception:
            pass

        # Broadcast status change to any connected TripProgressConsumer
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'trip.{trip.id}.progress',
                {
                    'type': 'status_change',
                    'new_status': 'awaiting_signature',
                    'tracking_status': 'arrived_at_dropoff',
                    'changed_at': now.isoformat(),
                    'message': 'Driver has arrived at dropoff. Awaiting passenger signature.',
                }
            )
        except Exception:
            pass

        return CustomResponse.success(
            message='Signature captured. Confirm to complete trip.',
            data={'signature_id': str(sig.id), 'trip_id': str(trip.id)},
            status_code=201
        )


class DriverStatusView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def patch(self, request):
        serializer = DriverStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        driver = request.driver
        new_status = serializer.validated_data['status']

        if new_status == 'offline':
            # Cannot go offline during active trip
            from apps.trips.models import Trip
            active = Trip.objects.filter(
                driver=driver, status__in=['on_way', 'in_progress', 'awaiting_signature']
            ).exists()
            if active:
                return CustomResponse.error(
                    'Cannot go offline while a trip is in progress.', 400
                )
            driver.status_availability = 'off_duty'
        else:
            driver.status_availability = 'available'

        driver.save(update_fields=['status_availability'])

        return CustomResponse.success(
            message='Status updated.',
            data={'driver_id': str(driver.id), 'availability_status': driver.status_availability},
            status_code=200
        )


class DriverLocationView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def post(self, request):
        serializer = DriverLocationUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        driver = request.driver

        # Discard updates from offline drivers silently
        if driver.status_availability == 'off_duty':
            return CustomResponse.success(message='Location update ignored — driver offline.', status_code=200)

        data = serializer.validated_data
        from apps.tracking.models import DriverLocation, ActiveTripTracking

        DriverLocation.objects.update_or_create(
            driver=driver,
            defaults={
                'provider': driver.provider,
                'latitude': data['latitude'],
                'longitude': data['longitude'],
                'heading': data.get('heading'),
                'speed': data.get('speed'),
                'is_online': True,
            }
        )

        # Update ActiveTripTracking if on a trip
        active_tracking = None
        try:
            active_tracking = ActiveTripTracking.objects.get(driver=driver)
            active_tracking.current_lat = data['latitude']
            active_tracking.current_lng = data['longitude']
            active_tracking.save(update_fields=['current_lat', 'current_lng'])
        except ActiveTripTracking.DoesNotExist:
            pass

        # Queue async history write (mirrors WebSocket path)
        try:
            from apps.tracking.tasks import write_location_history
            from django.utils import timezone
            trip_id = str(active_tracking.trip_id) if active_tracking else None
            write_location_history.delay(
                str(driver.id),
                float(data['latitude']),
                float(data['longitude']),
                timezone.now().isoformat(),
                trip_id,
            )
        except Exception:
            pass

        # Queue async ETA recomputation if on a trip (mirrors WebSocket path)
        if active_tracking:
            try:
                from apps.tracking.tasks import recompute_eta
                recompute_eta.delay(
                    str(active_tracking.id),
                    float(data['latitude']),
                    float(data['longitude']),
                )
            except Exception:
                pass

        # Broadcast to provider live map
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            from django.utils import timezone
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'provider.{driver.provider.id}.live_map',
                {
                    'type': 'driver_position',
                    'driver_id': str(driver.id),
                    'full_name': driver.full_name,
                    'latitude': float(data['latitude']),
                    'longitude': float(data['longitude']),
                    'heading': float(data['heading']) if data.get('heading') else None,
                    'speed': float(data['speed']) if data.get('speed') else None,
                    'status_availability': driver.status_availability,
                    'vehicle_type': driver.vehicle.vehicle_type if driver.vehicle else None,
                    'timestamp': timezone.now().isoformat(),
                }
            )
        except Exception:
            pass

        return CustomResponse.success(message='Location updated.', status_code=200)
