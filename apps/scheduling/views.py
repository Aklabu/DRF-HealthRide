from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from utils.response import CustomResponse
from .models import DailySchedule, ScheduleSlot, AIAssignmentLog
from .serializers import (
    ScheduleSlotSerializer,
    AutoAssignRequestSerializer,
    SlotReassignSerializer,
)
from .utils import (
    get_provider_today,
    vehicle_satisfies_requirements,
    driver_has_conflict,
    run_ai_assignment,
)


def get_or_create_schedule(provider, schedule_date):
    """Fetch or auto-create a DailySchedule for provider + date."""
    schedule, created = DailySchedule.objects.get_or_create(
        provider=provider,
        date=schedule_date,
    )
    if created:
        # Sync stats from any existing trips for this date
        schedule.refresh_stats()
    return schedule


def build_schedule_response(schedule, request):
    """Build the standard schedule response dict."""
    slots = schedule.slots.select_related(
        'trip', 'trip__passenger', 'trip__vehicle',
        'driver',
    ).prefetch_related('trip__passenger_contacts').order_by('trip__pickup_time')

    # Unassigned slots float to the top within their time group
    unassigned_slots = [s for s in slots if s.driver is None]
    assigned_slots = [s for s in slots if s.driver is not None]
    ordered_slots = unassigned_slots + assigned_slots

    slot_data = ScheduleSlotSerializer(ordered_slots, many=True, context={'request': request}).data

    return {
        'header': {
            'total_trips': schedule.total_trips,
            'completed_trips': schedule.completed_trips,
            'in_progress': schedule.in_progress,
            'scheduled': schedule.scheduled,
            'unassigned': schedule.unassigned,
        },
        'date': schedule.date,
        'slots': slot_data,
    }


# GET /scheduling/daily/ — today's schedule
class DailyScheduleTodayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = get_provider_today(request.user)
        schedule = get_or_create_schedule(request.user, today)

        return CustomResponse.success(
            message='Today\'s schedule fetched successfully.',
            data=build_schedule_response(schedule, request),
            status_code=200
        )


# GET /scheduling/daily/{date}/ — schedule for a specific date
class DailyScheduleDateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, date):
        # Validate date format
        from datetime import datetime as dt
        try:
            schedule_date = dt.strptime(str(date), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return CustomResponse.error(
                message='Invalid date format. Use YYYY-MM-DD.',
                status_code=400
            )

        schedule = get_or_create_schedule(request.user, schedule_date)

        return CustomResponse.success(
            message=f'Schedule for {schedule_date} fetched successfully.',
            data=build_schedule_response(schedule, request),
            status_code=200
        )


# POST /scheduling/auto-assign/ — AI auto-assignment for unassigned trips
class AutoAssignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AutoAssignRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Resolve target date
        schedule_date = data.get('date') or get_provider_today(request.user)

        # Fetch schedule — 404 if no schedule exists for this date
        try:
            schedule = DailySchedule.objects.get(
                provider=request.user,
                date=schedule_date,
            )
        except DailySchedule.DoesNotExist:
            return CustomResponse.error(
                message=f'No schedule found for {schedule_date}.',
                status_code=404
            )

        # Determine target slots
        if data.get('trip_ids'):
            # Specific trips requested — validate they belong to this provider and are unassigned
            slots = ScheduleSlot.objects.filter(
                schedule=schedule,
                trip__id__in=data['trip_ids'],
                trip__provider=request.user,
                driver__isnull=True,
                trip__status='scheduled',
            ).select_related('trip')
        else:
            # All unassigned scheduled slots for this date
            slots = ScheduleSlot.objects.filter(
                schedule=schedule,
                driver__isnull=True,
                trip__status='scheduled',
            ).select_related('trip')

        if not slots.exists():
            return CustomResponse.success(
                message='No unassigned trips for this date.',
                data={
                    'date': schedule_date,
                    'processed': 0,
                    'assigned': 0,
                    'failed': 0,
                    'results': [],
                },
                status_code=200
            )

        results = []
        assigned_count = 0
        failed_count = 0

        for slot in slots:
            trip = slot.trip

            with transaction.atomic():
                selected_driver, drivers_considered, reason = run_ai_assignment(
                    trip, request.user, schedule_date
                )

                if selected_driver:
                    # Apply assignment
                    slot.driver = selected_driver
                    slot.assigned_at = timezone.now()
                    slot.assignment_method = 'ai'
                    slot.save(update_fields=['driver', 'assigned_at', 'assignment_method'])

                    trip.driver = selected_driver
                    trip.vehicle = selected_driver.vehicle
                    trip.assigned_at = timezone.now()
                    trip.save(update_fields=['driver', 'vehicle', 'assigned_at'])

                    # Log the AI assignment
                    AIAssignmentLog.objects.create(
                        trip=trip,
                        provider=request.user,
                        drivers_considered=drivers_considered,
                        selected_driver=selected_driver,
                        assignment_successful=True,
                        reason=reason,
                    )

                    # Update schedule header counts
                    schedule.unassigned = max(0, schedule.unassigned - 1)
                    schedule.scheduled += 1
                    schedule.save(update_fields=['unassigned', 'scheduled'])

                    # Notify driver — fire and forget
                    try:
                        from apps.notifications.utils import notify_driver_assignment
                        notify_driver_assignment(trip, selected_driver)
                    except Exception:
                        pass

                    assigned_count += 1
                    results.append({
                        'trip_id': str(trip.id),
                        'pickup_time': trip.pickup_time,
                        'status': 'assigned',
                        'assigned_driver': {
                            'full_name': selected_driver.full_name,
                            'driver_id': str(selected_driver.id),
                        },
                        'reason': reason,
                    })

                else:
                    # Log failed attempt
                    AIAssignmentLog.objects.create(
                        trip=trip,
                        provider=request.user,
                        drivers_considered=drivers_considered,
                        selected_driver=None,
                        assignment_successful=False,
                        reason=reason,
                    )

                    failed_count += 1
                    results.append({
                        'trip_id': str(trip.id),
                        'pickup_time': trip.pickup_time,
                        'status': 'failed',
                        'assigned_driver': None,
                        'reason': reason,
                    })

        return CustomResponse.success(
            message='Auto-assignment completed.',
            data={
                'date': schedule_date,
                'processed': len(results),
                'assigned': assigned_count,
                'failed': failed_count,
                'results': results,
            },
            status_code=200
        )


# PATCH /scheduling/slots/{id}/ — manual driver reassignment
class ScheduleSlotReassignView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        # Scope to this provider via schedule
        slot = get_object_or_404(
            ScheduleSlot,
            id=id,
            schedule__provider=request.user,
        )

        # Only allow reassignment on scheduled trips
        if slot.trip.status != 'scheduled':
            return CustomResponse.error(
                message=f'Cannot reassign driver on a trip with status "{slot.trip.status}".',
                status_code=400
            )

        serializer = SlotReassignSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        driver_id = serializer.validated_data['driver_id']

        from apps.drivers.models import Driver
        try:
            new_driver = Driver.objects.get(id=driver_id, provider=request.user)
        except Driver.DoesNotExist:
            return CustomResponse.error(
                message='Driver not found or does not belong to your account.',
                status_code=404
            )

        # Driver must be actively employed
        if new_driver.status_employment != 'active':
            return CustomResponse.error(
                message='Driver is not currently active.',
                status_code=400
            )

        # Validate vehicle type satisfies trip requirements
        if not new_driver.vehicle:
            return CustomResponse.error(
                message='Driver has no vehicle assigned.',
                status_code=400
            )

        if not vehicle_satisfies_requirements(new_driver.vehicle, slot.trip.special_requirements):
            return CustomResponse.error(
                message=(
                    f'Driver vehicle type ({new_driver.vehicle.vehicle_type}) does not satisfy '
                    f'trip requirement ({slot.trip.special_requirements}).'
                ),
                status_code=400
            )

        # Check for schedule conflict on the same date
        pickup_time = slot.trip.pickup_time
        dropoff_time = slot.trip.approximate_dropoff_time or pickup_time
        schedule_date = slot.schedule.date

        has_conflict, conflicting_trip = driver_has_conflict(
            new_driver, schedule_date, pickup_time, dropoff_time, exclude_trip=slot.trip
        )
        if has_conflict:
            return CustomResponse.error(
                message=(
                    f'Driver already has a trip ({str(conflicting_trip.id)}) '
                    f'that conflicts with this time window.'
                ),
                status_code=400
            )

        previous_driver = slot.driver

        with transaction.atomic():
            # Clear old driver from trip if any
            if previous_driver and previous_driver != new_driver:
                slot.trip.driver = None
                slot.trip.vehicle = None
                slot.trip.save(update_fields=['driver', 'vehicle'])

            # Apply new assignment to slot
            was_unassigned = slot.driver is None
            slot.driver = new_driver
            slot.assigned_at = timezone.now()
            slot.assignment_method = 'manual'
            slot.save(update_fields=['driver', 'assigned_at', 'assignment_method'])

            # Sync to trip
            slot.trip.driver = new_driver
            slot.trip.vehicle = new_driver.vehicle
            slot.trip.assigned_at = timezone.now()
            slot.trip.save(update_fields=['driver', 'vehicle', 'assigned_at'])

            # Update schedule header counts if this was previously unassigned
            if was_unassigned:
                slot.schedule.unassigned = max(0, slot.schedule.unassigned - 1)
                slot.schedule.scheduled += 1
                slot.schedule.save(update_fields=['unassigned', 'scheduled'])

            # Create TripStatusLog entry
            from apps.trips.models import TripStatusLog
            TripStatusLog.objects.create(
                trip=slot.trip,
                from_status=slot.trip.status,
                to_status=slot.trip.status,
                changed_by='provider',
                notes=f'Manually reassigned to driver {new_driver.full_name} via scheduling.',
            )

            # Notify new driver — fire and forget
            try:
                from apps.notifications.utils import notify_driver_assignment
                notify_driver_assignment(slot.trip, new_driver)
            except Exception:
                pass

            # Notify old driver of unassignment — fire and forget
            if previous_driver and previous_driver != new_driver:
                try:
                    from apps.notifications.utils import notify_driver_unassignment
                    notify_driver_unassignment(slot.trip, previous_driver)
                except Exception:
                    pass

        return CustomResponse.success(
            message='Driver reassigned successfully.',
            data={
                'slot_id': str(slot.id),
                'trip_id': str(slot.trip.id),
                'date': schedule_date,
                'previous_driver': {
                    'full_name': previous_driver.full_name,
                    'driver_id': str(previous_driver.id),
                } if previous_driver else None,
                'new_driver': {
                    'full_name': new_driver.full_name,
                    'driver_id': str(new_driver.id),
                    'phone': new_driver.phone_number,
                },
                'new_vehicle': {
                    'vehicle_id': str(new_driver.vehicle.id),
                    'vehicle_type': new_driver.vehicle.vehicle_type,
                },
                'assignment_method': 'manual',
                'assigned_at': slot.assigned_at,
            },
            status_code=200
        )
