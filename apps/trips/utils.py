import requests
from decimal import Decimal
from datetime import datetime, timedelta, date
from django.conf import settings
from django.utils import timezone


# Call Google Maps Distance Matrix API — returns distance in miles and duration in minutes
def get_route_from_google_maps(pickup_address, dropoff_address):
    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')

    url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
    params = {
        'origins': pickup_address,
        'destinations': dropoff_address,
        'units': 'imperial',  # miles
        'key': api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if data.get('status') != 'OK':
            return None, 'Google Maps API returned an error. Please check the addresses.'

        element = data['rows'][0]['elements'][0]
        if element.get('status') != 'OK':
            return None, 'Could not calculate route between the given addresses.'

        # Distance in meters → miles
        distance_meters = element['distance']['value']
        distance_miles = round(distance_meters / 1609.344, 2)

        # Duration in seconds → minutes
        duration_seconds = element['duration']['value']
        duration_minutes = round(duration_seconds / 60)

        result = {
            'pickup_address': pickup_address,
            'dropoff_address': dropoff_address,
            'estimated_distance': distance_miles,
            'estimated_duration': duration_minutes,
            'route_type': 'fastest',
        }
        return result, None

    except requests.RequestException:
        return None, 'Failed to connect to Google Maps API.'


# Compute fare based on rate card and estimated distance
def compute_pricing(estimated_distance, special_requirements, provider, facility=None):
    estimated_distance = Decimal(str(estimated_distance))
    rate_source = 'provider_rate'
    base_fare = Decimal('0.00')
    miles_included = Decimal('0.00')
    per_mile_rate = Decimal('0.00')
    discount_percentage = Decimal('0.00')

    # Try facility-specific pricing first
    if facility:
        try:
            pricing = facility.pricing
            rate_source = 'facility_rate'

            if special_requirements in ('standard', 'oxygen'):
                base_fare = pricing.standard_sedan_rate
            elif special_requirements == 'wheelchair':
                base_fare = pricing.wheelchair_accessible_rate
            elif special_requirements == 'stretcher':
                base_fare = pricing.stretcher_transport_rate

            discount_percentage = pricing.discount_percentage or Decimal('0.00')
            # Facility pricing has no per-mile breakdown — full base fare model
            miles_included = Decimal('0.00')
            per_mile_rate = Decimal('0.00')

        except Exception:
            # Fall through to provider rate card
            rate_source = 'provider_rate'

    # Use provider rate card if no facility pricing or fallback
    if rate_source == 'provider_rate':
        try:
            rate_card = provider.rate_card

            if special_requirements in ('standard', 'oxygen'):
                base_fare = rate_card.standard_base_fare
                miles_included = rate_card.standard_miles_included
                per_mile_rate = rate_card.standard_per_mile_rate
            elif special_requirements == 'wheelchair':
                base_fare = rate_card.wheelchair_base_fare
                miles_included = rate_card.wheelchair_miles_included
                per_mile_rate = rate_card.wheelchair_per_mile_rate
            elif special_requirements == 'stretcher':
                base_fare = rate_card.stretcher_base_fare
                miles_included = rate_card.stretcher_miles_included
                per_mile_rate = rate_card.stretcher_per_mile_rate

        except Exception:
            # Rate card not configured — return zero pricing
            pass

    # Compute mileage cost
    billable_distance = max(Decimal('0.00'), estimated_distance - miles_included)
    mileage_cost = billable_distance * per_mile_rate
    subtotal = base_fare + mileage_cost

    # Apply discount if any
    discount_applied = Decimal('0.00')
    if discount_percentage > 0:
        discount_applied = subtotal * (discount_percentage / Decimal('100'))

    total_amount = subtotal - discount_applied

    return {
        'base_fare': round(base_fare, 2),
        'miles_included': round(miles_included, 2),
        'estimated_distance': round(estimated_distance, 2),
        'billable_distance': round(billable_distance, 2),
        'mileage_cost': round(mileage_cost, 2),
        'discount_applied': round(discount_applied, 2),
        'total_amount': round(total_amount, 2),
        'rate_source': rate_source,
    }


# Validate submitted pricing against server-computed values — tolerance of $0.10
def validate_pricing_match(submitted_base, submitted_mileage, submitted_total, computed):
    tolerance = Decimal('0.10')
    errors = {}

    if abs(Decimal(str(submitted_base)) - computed['base_fare']) > tolerance:
        errors['base_fare'] = 'Submitted base_fare does not match computed value.'
    if abs(Decimal(str(submitted_mileage)) - computed['mileage_cost']) > tolerance:
        errors['mileage_cost'] = 'Submitted mileage_cost does not match computed value.'
    if abs(Decimal(str(submitted_total)) - computed['total_amount']) > tolerance:
        errors['total_amount'] = 'Submitted total_amount does not match computed value.'

    return errors


# Compute approximate dropoff time by adding duration minutes to pickup time
def compute_dropoff_time(pickup_time, duration_minutes):
    pickup_dt = datetime.combine(date.today(), pickup_time)
    dropoff_dt = pickup_dt + timedelta(minutes=duration_minutes)
    return dropoff_dt.time()


# Generate all individual trip dates for a recurring config
def generate_recurring_dates(pickup_date, end_date, frequency, days_of_week):
    dates = []
    current = pickup_date

    while current <= end_date:
        if frequency == 'daily':
            dates.append(current)
        elif frequency == 'weekly':
            # days_of_week: 0=Monday … 6=Sunday
            if current.weekday() in days_of_week:
                dates.append(current)

        current += timedelta(days=1)

    return dates


# Attempt auto-assignment — returns (driver, vehicle) or (None, None)
def attempt_auto_assignment(trip, provider):
    try:
        settings_obj = provider.settings
        if not settings_obj.enable_auto_assignment:
            return None, None
    except Exception:
        return None, None

    from apps.drivers.models import Driver, DriverAvailability
    from apps.vehicles.models import Vehicle

    # Map special_requirements to vehicle type
    req_to_vehicle = {
        'standard': 'sedan',
        'oxygen': 'sedan',
        'wheelchair': 'wheelchair_accessible',
        'stretcher': 'stretcher',
    }
    required_vehicle_type = req_to_vehicle.get(trip.special_requirements, 'sedan')

    # Filter available drivers with correct vehicle type
    pickup_weekday = trip.pickup_date.weekday()
    candidates = Driver.objects.filter(
        provider=provider,
        status_availability='available',
        status_employment='active',
        vehicle__vehicle_type=required_vehicle_type,
    ).select_related('vehicle')

    # Filter by availability schedule — must be available on pickup day and within time window
    qualified = []
    for driver in candidates:
        try:
            avail = DriverAvailability.objects.get(
                driver=driver,
                day_of_week=pickup_weekday,
                is_available=True,
            )
            if avail.start_time <= trip.pickup_time <= avail.end_time:
                qualified.append(driver)
        except DriverAvailability.DoesNotExist:
            continue

    if not qualified:
        return None, None

    # Proximity ranking via tracking app — fallback to first qualified if unavailable
    assigned_driver = None
    try:
        from apps.tracking.models import DriverLocation
        pickup_addr = trip.pickup_address
        radius = settings_obj.auto_assignment_radius

        best = None
        best_dist = None
        for driver in qualified:
            try:
                loc = DriverLocation.objects.get(driver=driver)
                # Simple proximity check — tracking app provides coordinates
                dist = loc.distance_to_address(pickup_addr)
                if best_dist is None or dist < best_dist:
                    best = driver
                    best_dist = dist
            except Exception:
                continue

        assigned_driver = best or qualified[0]
    except Exception:
        # Tracking app unavailable — assign first qualified driver
        assigned_driver = qualified[0]

    if assigned_driver and assigned_driver.vehicle:
        return assigned_driver, assigned_driver.vehicle

    return None, None


# Handle all post-completion stat updates in one transaction block
def handle_trip_completion(trip):
    from django.db import transaction
    from apps.drivers.models import DriverWorkLog
    from apps.passengers.models import PassengerCommonLocation, PreferredDriver

    with transaction.atomic():
        # Compute trip duration in hours
        if trip.started_at and trip.completed_at:
            duration_seconds = (trip.completed_at - trip.started_at).total_seconds()
            hours_worked = Decimal(str(round(duration_seconds / 3600, 4)))
        else:
            hours_worked = Decimal('0.00')

        # Update or create DriverWorkLog
        if trip.driver:
            log, created = DriverWorkLog.objects.get_or_create(
                driver=trip.driver,
                date=trip.pickup_date,
                defaults={'status': 'worked', 'hours_worked': Decimal('0.00'), 'trips_completed': 0}
            )
            log.hours_worked = (log.hours_worked or Decimal('0.00')) + hours_worked
            log.trips_completed += 1
            log.status = 'worked'
            log.save()

            # Increment driver total_trips
            trip.driver.total_trips += 1
            trip.driver.save(update_fields=['total_trips'])

        # Increment passenger stats
        if trip.passenger:
            trip.passenger.total_trips += 1
            trip.passenger.completed_trips += 1
            trip.passenger.total_spent = (trip.passenger.total_spent or Decimal('0.00')) + trip.total_amount
            trip.passenger.save(update_fields=['total_trips', 'completed_trips', 'total_spent'])

            # Increment common location trip count if dropoff matches
            try:
                loc = PassengerCommonLocation.objects.get(
                    passenger=trip.passenger,
                    full_address=trip.dropoff_address
                )
                loc.trips_count += 1
                loc.save(update_fields=['trips_count'])
            except PassengerCommonLocation.DoesNotExist:
                pass

            # Update or create preferred driver record
            if trip.driver:
                pref, created = PreferredDriver.objects.get_or_create(
                    passenger=trip.passenger,
                    driver=trip.driver,
                    defaults={'trips_count': 0}
                )
                pref.trips_count += 1
                pref.save(update_fields=['trips_count'])

        # Update facility denormalized stats
        if trip.facility:
            today = timezone.now().date()
            month_start = today.replace(day=1)
            is_this_month = trip.pickup_date >= month_start

            trip.facility.total_trips += 1
            trip.facility.total_revenue = (trip.facility.total_revenue or Decimal('0.00')) + trip.total_amount

            if is_this_month:
                trip.facility.total_trips_this_month += 1
                trip.facility.total_revenue_this_month = (
                    trip.facility.total_revenue_this_month or Decimal('0.00')
                ) + trip.total_amount

            trip.facility.save(update_fields=[
                'total_trips', 'total_revenue',
                'total_trips_this_month', 'total_revenue_this_month'
            ])

        # Trigger billing app to process this trip
        try:
            from apps.billing.utils import handle_completed_trip
            handle_completed_trip(trip)
        except Exception:
            # Billing app not yet available — skip silently
            pass