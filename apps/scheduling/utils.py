from decimal import Decimal
from datetime import datetime, date
from django.utils import timezone


# Map trip special_requirements to required vehicle type
REQUIREMENTS_TO_VEHICLE = {
    'standard': ['sedan', 'wheelchair_accessible', 'stretcher'],
    'oxygen': ['sedan', 'wheelchair_accessible', 'stretcher'],
    'wheelchair': ['wheelchair_accessible'],
    'stretcher': ['stretcher'],
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
    """Return True if two time windows overlap."""
    return start1 < end2 and start2 < end1


def driver_has_conflict(driver, schedule_date, pickup_time, dropoff_time, exclude_trip=None):
    """
    Check if a driver already has a ScheduleSlot on schedule_date whose
    trip time window overlaps with pickup_time → dropoff_time.
    Optionally exclude a specific trip from the conflict check.
    """
    from .models import ScheduleSlot

    slots = ScheduleSlot.objects.filter(
        schedule__date=schedule_date,
        driver=driver,
    ).select_related('trip')

    if exclude_trip:
        slots = slots.exclude(trip=exclude_trip)

    for slot in slots:
        slot_start = slot.trip.pickup_time
        slot_end = slot.trip.approximate_dropoff_time or slot.trip.pickup_time

        if times_overlap(pickup_time, dropoff_time, slot_start, slot_end):
            return True, slot.trip

    return False, None


def vehicle_satisfies_requirements(vehicle, special_requirements):
    """Return True if the vehicle type satisfies the trip's special_requirements."""
    allowed = REQUIREMENTS_TO_VEHICLE.get(special_requirements, ['sedan'])
    return vehicle.vehicle_type in allowed


def get_driver_distance_to_address(driver, pickup_address):
    """
    Attempt to get straight-line distance from driver's last known location
    to pickup_address via the tracking app.
    Returns distance in miles, or a large fallback value if unavailable.
    """
    try:
        from apps.tracking.models import DriverLocation
        loc = DriverLocation.objects.get(driver=driver)
        if hasattr(loc, 'distance_to_address'):
            return float(loc.distance_to_address(pickup_address))
        # If coordinates are available, return a placeholder
        return 0.0
    except Exception:
        # Tracking app unavailable — return 0 so driver is not penalized
        return 0.0


def run_ai_assignment(trip, provider, schedule_date):
    """
    Run the AI assignment algorithm for a single trip.

    Returns:
        selected_driver (Driver or None),
        drivers_considered (list of scored candidate dicts),
        reason (str)
    """
    from apps.drivers.models import Driver, DriverAvailability
    from .models import ScheduleSlot

    pickup_time = trip.pickup_time
    dropoff_time = trip.approximate_dropoff_time or pickup_time
    pickup_weekday = schedule_date.weekday()

    # Step 1 — Candidate pool: all active drivers for this provider
    all_drivers = Driver.objects.filter(
        provider=provider,
        status_employment='active',
    ).select_related('vehicle')

    drivers_considered = []
    qualified = []

    for driver in all_drivers:
        candidate = {
            'driver_id': str(driver.id),
            'driver_name': driver.full_name,
            'distance_miles': None,
            'current_load': 0,
            'availability_match': False,
            'vehicle_match': False,
            'score': None,
            'eliminated_reason': None,
        }

        # Hard filter 1 — vehicle type match
        if not driver.vehicle:
            candidate['eliminated_reason'] = 'No vehicle assigned'
            drivers_considered.append(candidate)
            continue

        if not vehicle_satisfies_requirements(driver.vehicle, trip.special_requirements):
            candidate['eliminated_reason'] = (
                f'Vehicle type {driver.vehicle.vehicle_type} does not satisfy '
                f'{trip.special_requirements} requirement'
            )
            drivers_considered.append(candidate)
            continue

        candidate['vehicle_match'] = True

        # Hard filter 2 — availability schedule
        try:
            avail = DriverAvailability.objects.get(
                driver=driver,
                day_of_week=pickup_weekday,
                is_available=True,
            )
            if not (avail.start_time <= pickup_time <= avail.end_time):
                candidate['eliminated_reason'] = (
                    f'Pickup time {pickup_time} outside availability window '
                    f'{avail.start_time}–{avail.end_time}'
                )
                drivers_considered.append(candidate)
                continue
            candidate['availability_match'] = True
        except DriverAvailability.DoesNotExist:
            candidate['eliminated_reason'] = f'Not available on day {pickup_weekday}'
            drivers_considered.append(candidate)
            continue

        # Hard filter 3 — no schedule conflict
        has_conflict, conflicting_trip = driver_has_conflict(
            driver, schedule_date, pickup_time, dropoff_time, exclude_trip=trip
        )
        if has_conflict:
            candidate['eliminated_reason'] = (
                f'Schedule conflict with trip {str(conflicting_trip.id)}'
            )
            drivers_considered.append(candidate)
            continue

        # Passed all hard filters — compute score
        distance = get_driver_distance_to_address(driver, trip.pickup_address)
        current_load = ScheduleSlot.objects.filter(
            schedule__date=schedule_date,
            driver=driver,
        ).count()

        distance_score = distance
        load_score = current_load * 10
        final_score = distance_score + load_score

        candidate['distance_miles'] = round(distance, 2)
        candidate['current_load'] = current_load
        candidate['score'] = round(final_score, 2)

        drivers_considered.append(candidate)
        qualified.append((driver, final_score))

    if not qualified:
        return None, drivers_considered, 'No available drivers passed all hard filters for this trip.'

    # Step 4 — Sort by score ascending, select lowest
    qualified.sort(key=lambda x: x[1])
    selected_driver = qualified[0][0]

    reason = (
        f'Selected {selected_driver.full_name} with score '
        f'{qualified[0][1]:.2f} from {len(qualified)} qualified candidate(s).'
    )

    return selected_driver, drivers_considered, reason
