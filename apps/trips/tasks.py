from django.utils import timezone
from datetime import datetime


def mark_driver_absence_trips():
    """
    Periodic task: mark scheduled trips as 'driver_absence' when the driver
    did not start the trip at or after the pickup time.

    Conditions for driver_absence:
    - Trip status is 'scheduled'
    - Trip has a driver assigned
    - Pickup date is today
    - Current time has passed the pickup time (driver should have started by now)
    - Trip has not been started (started_at is null)

    Runs every minute via Celery Beat.
    """
    from .models import Trip, TripStatusLog

    now = timezone.now()
    today = now.date()
    current_time = now.time()

    # Find all scheduled trips today with a driver that are past pickup time and not started
    absent_trips = Trip.objects.filter(
        status='scheduled',
        driver__isnull=False,
        pickup_date=today,
        pickup_time__lte=current_time,
        started_at__isnull=True,
    ).select_related('driver')

    marked = 0

    for trip in absent_trips:
        trip.status = 'driver_absence'
        trip.save(update_fields=['status'])

        TripStatusLog.objects.create(
            trip=trip,
            from_status='scheduled',
            to_status='driver_absence',
            changed_by='system',
            notes=(
                f'Driver {trip.driver.full_name} did not start the trip at '
                f'scheduled pickup time {trip.pickup_time}.'
            ),
        )

        # Release driver back to available
        trip.driver.status_availability = 'available'
        trip.driver.save(update_fields=['status_availability'])

        marked += 1

    return f'mark_driver_absence_trips: marked {marked} trips as driver_absence'


# Celery task registration
try:
    from config.celery import app as celery_app

    mark_driver_absence_trips = celery_app.task(
        name='trips.mark_driver_absence_trips',
        ignore_result=False,
    )(mark_driver_absence_trips)

except Exception:
    # Celery not configured — task remains as a plain function
    pass
