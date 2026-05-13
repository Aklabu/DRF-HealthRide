import requests
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, date
from django.conf import settings
from django.utils import timezone


# Calculate route distance and duration using Google Maps API
def get_route_from_google_maps(pickup_address, dropoff_address):
    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')

    url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
    params = {
        'origins': pickup_address,
        'destinations': dropoff_address,
        'units': 'imperial',
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

        distance_meters = element['distance']['value']
        distance_miles = round(distance_meters / 1609.344, 2)

        duration_seconds = element['duration']['value']
        duration_minutes = round(duration_seconds / 60)

        # Geocode pickup and dropoff for coordinates
        pickup_coords = _geocode_address(pickup_address, api_key)
        dropoff_coords = _geocode_address(dropoff_address, api_key)

        result = {
            'pickup_address': pickup_address,
            'dropoff_address': dropoff_address,
            'estimated_distance': distance_miles,
            'estimated_duration': duration_minutes,
            'route_type': 'fastest',
            'pickup_latitude': pickup_coords[0] if pickup_coords else None,
            'pickup_longitude': pickup_coords[1] if pickup_coords else None,
            'dropoff_latitude': dropoff_coords[0] if dropoff_coords else None,
            'dropoff_longitude': dropoff_coords[1] if dropoff_coords else None,
        }
        return result, None

    except requests.RequestException:
        return None, 'Failed to connect to Google Maps API.'


# Convert address to latitude and longitude coordinates
def _geocode_address(address, api_key):
    try:
        url = 'https://maps.googleapis.com/maps/api/geocode/json'
        response = requests.get(url, params={'address': address, 'key': api_key}, timeout=5)
        data = response.json()
        if data.get('status') == 'OK':
            loc = data['results'][0]['geometry']['location']
            return loc['lat'], loc['lng']
    except Exception:
        pass
    return None


# Calculate trip fare based on distance, special requirements, and rate card
def compute_pricing_v2(estimated_distance, special_requirements, rate_card, trip_type='single'):
    """
    Compute pricing from provider rate card.
    Returns dict with baseFare, mileageRate, totalMileageCost, subtotal,
    tripMultiplier, estimatedTotal.
    """
    estimated_distance = Decimal(str(estimated_distance))

    # Load rates from rate card based on special requirement
    if special_requirements in ('standard', 'oxygen'):
        base_fare = Decimal(str(rate_card.standard_base_fare))
        miles_included = Decimal(str(rate_card.standard_miles_included))
        per_mile_rate = Decimal(str(rate_card.standard_per_mile_rate))
    elif special_requirements == 'wheelchair':
        base_fare = Decimal(str(rate_card.wheelchair_base_fare))
        miles_included = Decimal(str(rate_card.wheelchair_miles_included))
        per_mile_rate = Decimal(str(rate_card.wheelchair_per_mile_rate))
    elif special_requirements == 'stretcher':
        base_fare = Decimal(str(rate_card.stretcher_base_fare))
        miles_included = Decimal(str(rate_card.stretcher_miles_included))
        per_mile_rate = Decimal(str(rate_card.stretcher_per_mile_rate))
    else:
        base_fare = Decimal('0.00')
        miles_included = Decimal('0.00')
        per_mile_rate = Decimal('0.00')

    # Mileage cost = (distance - included miles) × per_mile_rate
    billable_distance = max(Decimal('0.00'), estimated_distance - miles_included)
    total_mileage_cost = billable_distance * per_mile_rate

    subtotal = base_fare + total_mileage_cost

    # Trip multiplier: single=1, recurring=2
    trip_multiplier = Decimal('2.00') if trip_type == 'recurring' else Decimal('1.00')

    estimated_total = subtotal * trip_multiplier

    return {
        'baseFare': round(base_fare, 2),
        'mileageRate': round(per_mile_rate, 2),
        'totalMileageCost': round(total_mileage_cost, 2),
        'subtotal': round(subtotal, 2),
        'tripMultiplier': round(trip_multiplier, 2),
        'estimatedTotal': round(estimated_total, 2),
    }


# Calculate pricing using provider or facility rate card (legacy support)
def compute_pricing(estimated_distance, special_requirements, provider, facility=None):
    estimated_distance = Decimal(str(estimated_distance))
    rate_source = 'provider_rate'
    base_fare = Decimal('0.00')
    miles_included = Decimal('0.00')
    per_mile_rate = Decimal('0.00')
    discount_percentage = Decimal('0.00')

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
            miles_included = Decimal('0.00')
            per_mile_rate = Decimal('0.00')
        except Exception:
            rate_source = 'provider_rate'

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
            pass

    billable_distance = max(Decimal('0.00'), estimated_distance - miles_included)
    mileage_cost = billable_distance * per_mile_rate
    subtotal = base_fare + mileage_cost

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


# Map special requirements to vehicle types for driver matching
# Driver availability helpers
def get_available_drivers(provider, special_requirements, pickup_date, pickup_time):
    """
    Return list of available driver dicts sorted by rating (on_time_rate) descending.
    """
    from apps.drivers.models import Driver, DriverAvailability

    required_vehicle_type = REQ_TO_VEHICLE.get(special_requirements, 'sedan')
    pickup_weekday = pickup_date.weekday()

    candidates = Driver.objects.filter(
        provider=provider,
        status_employment='active',
        status_availability='available',
        vehicle__vehicle_type=required_vehicle_type,
    ).select_related('vehicle').order_by('-on_time_rate')

    result = []
    for driver in candidates:
        try:
            avail = DriverAvailability.objects.get(
                driver=driver,
                day_of_week=pickup_weekday,
                is_available=True,
            )
            if avail.start_time <= pickup_time <= avail.end_time:
                result.append({
                    'driverId': str(driver.id),
                    'name': driver.full_name,
                    'rating': float(driver.on_time_rate),
                    'availableAt': str(avail.start_time),
                    'vehicleType': driver.vehicle.vehicle_type if driver.vehicle else None,
                    'specialization': special_requirements,
                })
        except DriverAvailability.DoesNotExist:
            continue

    return result


# Find the earliest available driver matching vehicle type and availability
def find_earliest_available_driver(provider, required_vehicle_type, exclude_driver_id=None):
    from apps.drivers.models import Driver, DriverAvailability

    qs = Driver.objects.filter(
        provider=provider,
        status_employment='active',
        vehicle__vehicle_type=required_vehicle_type,
    ).select_related('vehicle').order_by('-on_time_rate')

    if exclude_driver_id:
        qs = qs.exclude(id=exclude_driver_id)

    alternatives = []
    best_driver = None

    for driver in qs:
        # Find their next available slot
        avail_slots = DriverAvailability.objects.filter(
            driver=driver,
            is_available=True,
        ).order_by('day_of_week')

        if avail_slots.exists():
            slot = avail_slots.first()
            alternatives.append({
                'driverId': str(driver.id),
                'name': driver.full_name,
                'specialization': required_vehicle_type,
                'availableAt': str(slot.start_time),
            })
            if best_driver is None:
                best_driver = driver

    return best_driver, alternatives[:5]  # return top 5 alternatives


# Calculate approximate dropoff time based on pickup time and estimated duration
def compute_dropoff_time(pickup_time, duration_minutes):
    pickup_dt = datetime.combine(date.today(), pickup_time)
    dropoff_dt = pickup_dt + timedelta(minutes=duration_minutes)
    return dropoff_dt.time()


# Generate and send payment link to passenger via SMS or email
def stub_send_payment_link(trip, delivery_method, contact):
    """
    Stub for payment link generation and delivery.
    Replace with real payment gateway integration.
    """
    stub_link = f'https://pay.healthride.example.com/trip/{trip.id}?token={uuid.uuid4().hex}'

    delivery_target = None
    if contact:
        delivery_target = contact.phone_number if delivery_method == 'sms' else contact.email

    # Log stub action
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        f'[STUB] Payment link for trip {trip.trip_number} '
        f'sent via {delivery_method} to {delivery_target}: {stub_link}'
    )

    return {
        'link': stub_link,
        'deliveryMethod': delivery_method,
        'deliveryStatus': 'sent',
        'phoneOrEmail': delivery_target,
    }


# Send trip confirmation notifications to passenger and driver
def stub_send_confirmation(trip, contact):
    """
    Stub for SMS/email confirmation to passenger and driver notification.
    Replace with real SMS/email service integration.
    """
    import logging
    logger = logging.getLogger(__name__)

    passenger_sms = False
    passenger_email = False
    driver_notification = False

    if contact:
        logger.info(f'[STUB] SMS confirmation sent to {contact.phone_number} for trip {trip.trip_number}')
        passenger_sms = True
        if contact.email:
            logger.info(f'[STUB] Email confirmation sent to {contact.email} for trip {trip.trip_number}')
            passenger_email = True

    if trip.driver:
        logger.info(f'[STUB] Driver notification sent to {trip.driver.full_name} for trip {trip.trip_number}')
        driver_notification = True

    return {
        'passengerSms': passenger_sms,
        'passengerEmail': passenger_email,
        'driverNotification': driver_notification,
    }


# Update driver and passenger statistics after trip completion
def handle_trip_completion(trip):
    from django.db import transaction
    from apps.drivers.models import DriverWorkLog
    from apps.passengers.models import PassengerCommonLocation, PreferredDriver

    with transaction.atomic():
        if trip.started_at and trip.completed_at:
            duration_seconds = (trip.completed_at - trip.started_at).total_seconds()
            hours_worked = Decimal(str(round(duration_seconds / 3600, 4)))
        else:
            hours_worked = Decimal('0.00')

        if trip.driver:
            log, _ = DriverWorkLog.objects.get_or_create(
                driver=trip.driver,
                date=trip.pickup_date,
                defaults={'status': 'worked', 'hours_worked': Decimal('0.00'), 'trips_completed': 0}
            )
            log.hours_worked = (log.hours_worked or Decimal('0.00')) + hours_worked
            log.trips_completed += 1
            log.status = 'worked'
            log.save()

            trip.driver.total_trips += 1
            trip.driver.save(update_fields=['total_trips'])

        if trip.passenger:
            trip.passenger.total_trips += 1
            trip.passenger.completed_trips += 1
            trip.passenger.total_spent = (
                trip.passenger.total_spent or Decimal('0.00')
            ) + trip.estimated_total
            trip.passenger.save(update_fields=['total_trips', 'completed_trips', 'total_spent'])

            try:
                loc = PassengerCommonLocation.objects.get(
                    passenger=trip.passenger,
                    full_address=trip.dropoff_address
                )
                loc.trips_count += 1
                loc.save(update_fields=['trips_count'])
            except PassengerCommonLocation.DoesNotExist:
                pass

            if trip.driver:
                pref, _ = PreferredDriver.objects.get_or_create(
                    passenger=trip.passenger,
                    driver=trip.driver,
                    defaults={'trips_count': 0}
                )
                pref.trips_count += 1
                pref.save(update_fields=['trips_count'])

        if trip.facility:
            today = timezone.now().date()
            month_start = today.replace(day=1)
            is_this_month = trip.pickup_date >= month_start

            trip.facility.total_trips += 1
            trip.facility.total_revenue = (
                trip.facility.total_revenue or Decimal('0.00')
            ) + trip.estimated_total

            if is_this_month:
                trip.facility.total_trips_this_month += 1
                trip.facility.total_revenue_this_month = (
                    trip.facility.total_revenue_this_month or Decimal('0.00')
                ) + trip.estimated_total

            trip.facility.save(update_fields=[
                'total_trips', 'total_revenue',
                'total_trips_this_month', 'total_revenue_this_month'
            ])

        try:
            from apps.billing.utils import handle_completed_trip
            handle_completed_trip(trip)
        except Exception:
            pass
