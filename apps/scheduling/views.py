from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from utils.response import CustomResponse
from apps.trips.models import Trip, TripStatusLog
from apps.trips.utils import compute_dropoff_time
from .models import DailySchedule, ScheduleSlot
from .serializers import (
    ScheduledTripSerializer,
    UnassignedTripSerializer,
    ScheduledTripUpdateSerializer,
)
from .utils import (
    vehicle_satisfies_requirements,
    driver_has_conflict,
    find_best_driver,
)


def _parse_date(raw):
    # Parse a YYYY-MM-DD string and return a date object, or None on failure
    try:
        return datetime.strptime(str(raw), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _trip_queryset(provider):
    # Base queryset for trips scoped to a provider with common select/prefetch
    return (
        Trip.objects.filter(provider=provider)
        .select_related('driver', 'vehicle', 'passenger')
        .prefetch_related('passenger_contacts')
    )


# Return daily trip statistics for a specific date
class SchedulingHeaderView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw_date = request.query_params.get('date')
        if not raw_date:
            return CustomResponse.error(message='date query parameter is required.', status_code=400)

        target_date = _parse_date(raw_date)
        if not target_date:
            return CustomResponse.error(message='Invalid date format. Use YYYY-MM-DD.', status_code=400)

        trips = Trip.objects.filter(provider=request.user, pickup_date=target_date)

        total_trips = trips.count()
        completed_trips = trips.filter(status='completed').count()
        in_progress = trips.filter(status__in=['in_progress', 'on_way']).count()
        scheduled_trips = trips.filter(status='scheduled', driver__isnull=False).count()
        unassigned_trips = trips.filter(
            Q(status='unassigned') |
            Q(status='driver_absence') |
            Q(status='scheduled', driver__isnull=True)
        ).count()

        return CustomResponse.success(
            message='Scheduling header fetched successfully.',
            data={
                'date': str(target_date),
                'totalTrips': total_trips,
                'completedTrips': completed_trips,
                'inProgress': in_progress,
                'scheduledTrips': scheduled_trips,
                'unassignedTrips': unassigned_trips,
            },
            status_code=200,
        )


# Return all scheduled trips with assigned drivers for a specific date
class ScheduledTripListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw_date = request.query_params.get('date')
        if not raw_date:
            return CustomResponse.error(message='date query parameter is required.', status_code=400)

        target_date = _parse_date(raw_date)
        if not target_date:
            return CustomResponse.error(message='Invalid date format. Use YYYY-MM-DD.', status_code=400)

        trips = (
            _trip_queryset(request.user)
            .filter(pickup_date=target_date, status='scheduled', driver__isnull=False)
            .order_by('pickup_time')
        )

        serializer = ScheduledTripSerializer(trips, many=True)
        return CustomResponse.success(
            message='Scheduled trips fetched successfully.',
            data=serializer.data,
            status_code=200,
        )


# Update pickup time or assigned driver for a scheduled trip on a specific date
class ScheduledTripUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, trip_id):
        raw_date = request.query_params.get('date')
        if not raw_date:
            return CustomResponse.error(message='date query parameter is required.', status_code=400)

        target_date = _parse_date(raw_date)
        if not target_date:
            return CustomResponse.error(message='Invalid date format. Use YYYY-MM-DD.', status_code=400)

        try:
            trip = _trip_queryset(request.user).get(id=trip_id, pickup_date=target_date)
        except Trip.DoesNotExist:
            return CustomResponse.error(message='Trip not found.', status_code=404)

        if trip.status != 'scheduled':
            return CustomResponse.error(
                message=f'Only scheduled trips can be updated. Current status: {trip.status}.',
                status_code=400,
            )

        serializer = ScheduledTripUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors,
            )

        data = serializer.validated_data
        update_fields = []

        with transaction.atomic():
            if 'driver_id' in data:
                from apps.drivers.models import Driver

                try:
                    new_driver = Driver.objects.select_related('vehicle').get(
                        id=data['driver_id'], provider=request.user
                    )
                except Driver.DoesNotExist:
                    return CustomResponse.error(
                        message='Driver not found or does not belong to your account.',
                        status_code=404,
                    )

                if new_driver.status_employment != 'active':
                    return CustomResponse.error(
                        message='Driver is not currently active.', status_code=400
                    )

                if not new_driver.vehicle:
                    return CustomResponse.error(
                        message='Driver has no vehicle assigned.', status_code=400
                    )

                if not vehicle_satisfies_requirements(new_driver.vehicle, trip.special_requirements):
                    return CustomResponse.error(
                        message=(
                            f'Driver vehicle type ({new_driver.vehicle.vehicle_type}) does not '
                            f'satisfy trip requirement ({trip.special_requirements}).'
                        ),
                        status_code=400,
                    )

                pickup_time = data.get('pickup_time') or trip.pickup_time
                dropoff_time = trip.approximate_dropoff_time or pickup_time
                has_conflict, conflicting = driver_has_conflict(
                    new_driver, target_date, pickup_time, dropoff_time, exclude_trip=trip
                )
                if has_conflict:
                    return CustomResponse.error(
                        message=f'Driver has a conflicting trip ({conflicting.trip_number}) on this date.',
                        status_code=400,
                    )

                trip.driver = new_driver
                trip.vehicle = new_driver.vehicle
                trip.assigned_at = timezone.now()
                update_fields += ['driver', 'vehicle', 'assigned_at']

            if 'pickup_time' in data:
                trip.pickup_time = data['pickup_time']
                update_fields.append('pickup_time')

                # Recompute approximate_dropoff_time using stored estimated_duration
                duration = int(trip.estimated_duration or 0)
                if duration > 0:
                    trip.approximate_dropoff_time = compute_dropoff_time(data['pickup_time'], duration)
                    update_fields.append('approximate_dropoff_time')

            if update_fields:
                trip.save(update_fields=update_fields)

            TripStatusLog.objects.create(
                trip=trip,
                from_status=trip.status,
                to_status=trip.status,
                changed_by='provider',
                notes='Trip updated via scheduling.',
            )

        trip.refresh_from_db()
        serializer = ScheduledTripSerializer(
            Trip.objects.select_related('driver', 'vehicle', 'passenger')
            .prefetch_related('passenger_contacts')
            .get(pk=trip.pk)
        )
        return CustomResponse.success(
            message='Trip updated successfully.',
            data=serializer.data,
            status_code=200,
        )


# Return all unassigned and driver_absence trips for a specific date
class UnassignedTripListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw_date = request.query_params.get('date')
        if not raw_date:
            return CustomResponse.error(message='date query parameter is required.', status_code=400)

        target_date = _parse_date(raw_date)
        if not target_date:
            return CustomResponse.error(message='Invalid date format. Use YYYY-MM-DD.', status_code=400)

        trips = (
            _trip_queryset(request.user)
            .filter(
                pickup_date=target_date,
                status__in=['unassigned', 'driver_absence'],
            )
            .order_by('pickup_time')
        )

        serializer = UnassignedTripSerializer(trips, many=True)
        return CustomResponse.success(
            message='Unassigned trips fetched successfully.',
            data=serializer.data,
            status_code=200,
        )


# Auto-assign the best available driver to each unassigned trip on a specific date
class AutoAssignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_date = request.query_params.get('date')
        if not raw_date:
            return CustomResponse.error(message='date query parameter is required.', status_code=400)

        target_date = _parse_date(raw_date)
        if not target_date:
            return CustomResponse.error(message='Invalid date format. Use YYYY-MM-DD.', status_code=400)

        trips = (
            Trip.objects.filter(
                provider=request.user,
                pickup_date=target_date,
                status__in=['unassigned', 'driver_absence'],
            )
            .select_related('driver', 'vehicle', 'passenger')
            .prefetch_related('passenger_contacts')
            .order_by('pickup_time')
        )

        if not trips.exists():
            return CustomResponse.success(
                message='No unassigned trips for this date.',
                data={
                    'date': str(target_date),
                    'processed': 0,
                    'assigned': 0,
                    'failed': 0,
                    'results': [],
                },
                status_code=200,
            )

        results = []
        assigned_count = 0
        failed_count = 0

        for trip in trips:
            driver, assignment_type, reason = find_best_driver(trip, request.user, target_date)

            if driver:
                with transaction.atomic():
                    from_status = trip.status
                    trip.driver = driver
                    trip.vehicle = driver.vehicle
                    trip.status = 'scheduled'
                    trip.assigned_at = timezone.now()
                    trip.save(update_fields=['driver', 'vehicle', 'status', 'assigned_at'])

                    TripStatusLog.objects.create(
                        trip=trip,
                        from_status=from_status,
                        to_status='scheduled',
                        changed_by='system',
                        notes='Auto-assigned by scheduling system.',
                    )

                    # Upsert ScheduleSlot to keep scheduling model in sync
                    schedule, _ = DailySchedule.objects.get_or_create(
                        provider=request.user,
                        date=target_date,
                    )
                    slot, slot_created = ScheduleSlot.objects.get_or_create(
                        schedule=schedule,
                        trip=trip,
                        defaults={
                            'driver': driver,
                            'assigned_at': timezone.now(),
                            'assignment_method': 'ai',
                        },
                    )
                    if not slot_created:
                        slot.driver = driver
                        slot.assigned_at = timezone.now()
                        slot.assignment_method = 'ai'
                        slot.save(update_fields=['driver', 'assigned_at', 'assignment_method'])

                assigned_count += 1
                results.append({
                    'trip_id': str(trip.id),
                    'trip_number': trip.trip_number,
                    'status': 'assigned',
                    'assigned_driver_id': str(driver.id),
                    'assigned_driver_name': driver.full_name,
                    'assignment_type': assignment_type,
                    'reason': reason,
                })
            else:
                failed_count += 1
                results.append({
                    'trip_id': str(trip.id),
                    'trip_number': trip.trip_number,
                    'status': 'failed',
                    'assigned_driver_id': None,
                    'assigned_driver_name': None,
                    'assignment_type': None,
                    'reason': reason,
                })

        return CustomResponse.success(
            message='Auto-assignment completed.',
            data={
                'date': str(target_date),
                'processed': len(results),
                'assigned': assigned_count,
                'failed': failed_count,
                'results': results,
            },
            status_code=200,
        )
