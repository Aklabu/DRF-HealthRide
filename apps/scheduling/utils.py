from datetime import datetime, timedelta
from django.utils import timezone


# Map special_requirements to the exact vehicle_type required
REQ_TO_VEHICLE = {
    'standard': 'sedan',
    'oxygen': 'sedan',
    'wheelchair': 'wheelchair_accessible',
    'stretcher': 'stretcher',
}


def get_provider_today(provider):
    """Return today's date in the provider's configured timezone."""
    import pytz
    tz_name = getattr(provider, 'timezone', 'UTC') or 'UTC'
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.UTC
    return timezone.now().astimezone(tz).date()


def times_overlap(start1, end1, start2, end2):
    """Return True if two time windows [start1, end1) and [start2, end2) overlap."""
    return start1 < end2 and start2 < end1


def driver_has_conflict(driver, schedule_date, pickup_time, dropoff_time, exclude_trip=None):
    """
    Return (True, conflicting_trip) if driver has an overlapping trip on schedule_date,
    otherwise (False, None). Optionally exclude a specific trip from the check.
    """
    from apps.trips.models import Trip

    qs = Trip.objects.filter(
        driver=driver,
        pickup_date=schedule_date,
        status__in=['scheduled', 'on_way', 'in_progress'],
    )
    if exclude_trip:
        qs = qs.exclude(pk=exclude_trip.pk)

    for trip in qs:
        slot_start = trip.pickup_time
        slot_end = trip.approximate_dropoff_time or trip.pickup_time
        if times_overlap(pickup_time, dropoff_time, slot_start, slot_end):
            return True, trip

    return False, None


def vehicle_satisfies_requirements(vehicle, special_requirements):
    """Return True if the vehicle's type matches the requirement."""
    required = REQ_TO_VEHICLE.get(special_requirements, 'sedan')
    return vehicle.vehicle_type == required


def find_best_driver(trip, provider, schedule_date):
    """
    Find the best driver for a trip on schedule_date.

    Strategy:
      1. Exact match — active driver, correct vehicle type, available on the weekday,
         pickup_time within availability window, no schedule conflict.
      2. Next available — among drivers with correct vehicle type, find the one whose
         last trip on that date ends soonest (smallest approximate_dropoff_time).
      3. No driver found — returns (None, None, reason).
    """
    from apps.drivers.models import Driver, DriverAvailability
    from apps.trips.models import Trip

    pickup_time = trip.pickup_time
    dropoff_time = trip.approximate_dropoff_time or pickup_time
    pickup_weekday = schedule_date.weekday()
    required_vehicle_type = REQ_TO_VEHICLE.get(trip.special_requirements, 'sedan')

    # Pool: active drivers with the correct vehicle type
    candidates = Driver.objects.filter(
        provider=provider,
        status_employment='active',
        vehicle__vehicle_type=required_vehicle_type,
    ).select_related('vehicle').order_by('-on_time_rate')

    # Pass 1 — exact match at pickup time
    for driver in candidates:
        try:
            avail = DriverAvailability.objects.get(
                driver=driver,
                day_of_week=pickup_weekday,
                is_available=True,
            )
        except DriverAvailability.DoesNotExist:
            continue

        if not (avail.start_time <= pickup_time <= avail.end_time):
            continue

        has_conflict, _ = driver_has_conflict(driver, schedule_date, pickup_time, dropoff_time)
        if has_conflict:
            continue

        return driver, 'exact_match', 'Driver available at pickup time'

    # Pass 2 — next available: driver who finishes their last trip soonest
    best_driver = None
    best_free_at = None

    for driver in candidates:
        last_trip = (
            Trip.objects.filter(
                driver=driver,
                pickup_date=schedule_date,
                status__in=['scheduled', 'on_way', 'in_progress'],
            )
            .order_by('-approximate_dropoff_time')
            .first()
        )
        free_at = last_trip.approximate_dropoff_time if last_trip else None

        # Driver has no trips that day — treat as immediately free
        if free_at is None:
            free_at = pickup_time

        if best_free_at is None or free_at < best_free_at:
            best_free_at = free_at
            best_driver = driver

    if best_driver:
        reason = f'No driver at pickup time. Assigned next available driver free at {best_free_at}.'
        return best_driver, 'next_available', reason

    return None, None, 'No drivers available for this trip.'
