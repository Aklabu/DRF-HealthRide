from decimal import Decimal
from datetime import timedelta, date
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Q


# Constants for report caching TTLs
DASHBOARD_TTL_MINUTES = 5
REPORT_TTL_TODAY_HOURS = 1       # range includes today — data still changing
REPORT_TTL_HISTORICAL_HOURS = 24  # fully historical — data is stable


def get_report_ttl(date_range_end):
    # Return expires_at datetime based on whether range includes today
    today = timezone.now().date()
    now = timezone.now()
    if date_range_end >= today:
        return now + timedelta(hours=REPORT_TTL_TODAY_HOURS)
    return now + timedelta(hours=REPORT_TTL_HISTORICAL_HOURS)


def get_dashboard_expires_at():
    return timezone.now() + timedelta(minutes=DASHBOARD_TTL_MINUTES)


# Snapshot helpers for caching report results
def get_valid_snapshot(provider, report_type, start, end):
    """Return a valid (non-expired) ReportSnapshot or None."""
    from .models import ReportSnapshot
    try:
        snap = ReportSnapshot.objects.get(
            provider=provider,
            report_type=report_type,
            date_range_start=start,
            date_range_end=end,
        )
        if snap.is_valid():
            return snap
    except ReportSnapshot.DoesNotExist:
        pass
    return None


def upsert_snapshot(provider, report_type, start, end, data):
    # Create or update a ReportSnapshot for the given range
    from .models import ReportSnapshot
    now = timezone.now()
    expires_at = get_report_ttl(end)
    ReportSnapshot.objects.update_or_create(
        provider=provider,
        report_type=report_type,
        date_range_start=start,
        date_range_end=end,
        defaults={
            'data': data,
            'generated_at': now,
            'expires_at': expires_at,
        }
    )


# Group a Trip queryset by day/week/month and pivot into period → counts
def group_trips_by_period(trips_qs, group_by, date_field='pickup_date'):

    from apps.trips.models import Trip
    from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

    trunc_map = {
        'day': TruncDay,
        'week': TruncWeek,
        'month': TruncMonth,
    }
    trunc_fn = trunc_map.get(group_by, TruncDay)

    rows = (
        trips_qs
        .annotate(period=trunc_fn(date_field))
        .values('period', 'status', 'payment_method')
        .annotate(count=Count('id'))
        .order_by('period')
    )

    # Pivot into period → counts
    periods = {}
    for row in rows:
        p = str(row['period'].date()) if hasattr(row['period'], 'date') else str(row['period']) if row['period'] else 'unknown'
        if p not in periods:
            periods[p] = {'period': p, 'total': 0, 'medicaid': 0, 'private_pay': 0, 'cancelled': 0}
        periods[p]['total'] += row['count']
        if row['payment_method'] == 'insurance':
            periods[p]['medicaid'] += row['count']
        elif row['payment_method'] in ('cash', 'card'):
            periods[p]['private_pay'] += row['count']
        if row['status'] == 'cancelled':
            periods[p]['cancelled'] += row['count']

    return sorted(periods.values(), key=lambda x: x['period'])



# Trip Volume report
def compute_trip_volume(provider, start, end, group_by=None):
    from apps.trips.models import Trip

    base_qs = Trip.objects.filter(
        provider=provider,
        pickup_date__gte=start,
        pickup_date__lte=end,
    )

    total = base_qs.exclude(status='cancelled').count()
    medicaid = base_qs.filter(payment_method='insurance').exclude(status='cancelled').count()
    private_pay = base_qs.filter(
        payment_method__in=['cash', 'card']
    ).exclude(status='cancelled').count()
    cancelled = base_qs.filter(status='cancelled').count()
    completed = base_qs.filter(status='completed').count()

    total_including_cancelled = total + cancelled
    completion_rate = (
        round((completed / total_including_cancelled) * 100, 2)
        if total_including_cancelled > 0 else 0.0
    )

    result = {
        'date_range': {'start': str(start), 'end': str(end)},
        'totals': {
            'total_trips': total,
            'medicaid_trips': medicaid,
            'private_pay_trips': private_pay,
            'cancelled_trips': cancelled,
            'completion_rate': completion_rate,
        },
    }

    if group_by:
        result['series'] = group_trips_by_period(base_qs, group_by)

    return result


# Driver Hours report
def compute_driver_hours(provider, start, end, group_by=None, driver_id=None):
    from apps.drivers.models import DriverWorkLog, Driver
    from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

    qs = DriverWorkLog.objects.filter(
        driver__provider=provider,
        date__gte=start,
        date__lte=end,
        status='worked',
    )

    if driver_id:
        qs = qs.filter(driver__id=driver_id)

    totals = qs.aggregate(
        total_hours=Sum('hours_worked'),
        total_trips=Sum('trips_completed'),
        total_earnings=Sum('earnings'),
    )
    total_hours = totals['total_hours'] or Decimal('0.00')

    active_drivers = qs.values('driver').distinct().count()
    avg_hours = (
        round(float(total_hours) / active_drivers, 2)
        if active_drivers > 0 else 0.0
    )

    # Overtime: hours > 8 per driver per day
    daily_logs = qs.values('driver', 'date').annotate(day_hours=Sum('hours_worked'))
    overtime_hours = sum(
        max(0, float(row['day_hours']) - 8)
        for row in daily_logs
        if row['day_hours']
    )

    # Per-driver breakdown
    driver_rows = (
        qs.values('driver__id', 'driver__full_name')
        .annotate(
            total_hours=Sum('hours_worked'),
            total_trips=Sum('trips_completed'),
            total_earnings=Sum('earnings'),
        )
        .order_by('-total_hours')
    )

    drivers_list = [
        {
            'driver_id': str(row['driver__id']),
            'driver_name': row['driver__full_name'],
            'total_hours': str(row['total_hours'] or '0.00'),
            'total_trips': row['total_trips'] or 0,
            'total_earnings': str(row['total_earnings'] or '0.00'),
        }
        for row in driver_rows
    ]

    result = {
        'date_range': {'start': str(start), 'end': str(end)},
        'totals': {
            'total_hours': str(total_hours),
            'active_drivers': active_drivers,
            'avg_hours_per_driver': avg_hours,
            'overtime_hours': round(overtime_hours, 2),
        },
        'drivers': drivers_list,
    }

    if group_by:
        trunc_map = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth}
        trunc_fn = trunc_map.get(group_by, TruncDay)
        series_rows = (
            qs.annotate(period=trunc_fn('date'))
            .values('period')
            .annotate(
                total_hours=Sum('hours_worked'),
                driver_count=Count('driver', distinct=True),
            )
            .order_by('period')
        )
        result['series'] = [
            {
                'period': str(row['period'].date()) if hasattr(row['period'], 'date') else str(row['period']),
                'total_hours': str(row['total_hours'] or '0.00'),
                'driver_count': row['driver_count'],
            }
            for row in series_rows
        ]

    return result


# Passenger Service report
def compute_passenger_service(provider, start, end, group_by=None):
    from apps.passengers.models import Passenger
    from apps.trips.models import Trip
    from django.db.models.functions import TruncWeek, TruncMonth
    from datetime import datetime, time as dt_time
    import pytz

    active_passengers = Passenger.objects.filter(
        provider=provider, status='active'
    ).count()

    new_passengers = Passenger.objects.filter(
        provider=provider,
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).count()

    completed_trips = Trip.objects.filter(
        provider=provider,
        status='completed',
        pickup_date__gte=start,
        pickup_date__lte=end,
    )
    total_completed = completed_trips.count()

    # On-time rate: actual pickup ≤ scheduled + 10 min grace
    # We use started_at vs pickup_date+pickup_time as proxy
    grace_minutes = 10
    try:
        grace_minutes = provider.settings.default_trip_lead_time or 10
    except Exception:
        pass

    on_time_count = 0
    for trip in completed_trips.only('pickup_date', 'pickup_time', 'started_at'):
        if not trip.started_at:
            continue
        tz = timezone.get_current_timezone()
        scheduled_dt = timezone.make_aware(
            datetime.combine(trip.pickup_date, trip.pickup_time), tz
        )
        deadline = scheduled_dt + timedelta(minutes=grace_minutes)
        if trip.started_at <= deadline:
            on_time_count += 1

    on_time_rate = (
        round((on_time_count / total_completed) * 100, 2)
        if total_completed > 0 else 0.0
    )

    avg_trips = (
        round(total_completed / active_passengers, 2)
        if active_passengers > 0 else 0.0
    )

    # Mobility breakdown
    mobility_rows = (
        completed_trips
        .values('passenger__mobility')
        .annotate(trip_count=Count('id'))
        .order_by('-trip_count')
    )
    mobility_breakdown = [
        {
            'mobility_type': row['passenger__mobility'] or 'unknown',
            'trip_count': row['trip_count'],
        }
        for row in mobility_rows
    ]

    result = {
        'date_range': {'start': str(start), 'end': str(end)},
        'totals': {
            'active_passengers': active_passengers,
            'new_passengers': new_passengers,
            'total_trips': total_completed,
            'on_time_rate': on_time_rate,
            'avg_trips_per_passenger': avg_trips,
        },
        'mobility_breakdown': mobility_breakdown,
    }

    if group_by:
        trunc_map = {'week': TruncWeek, 'month': TruncMonth}
        trunc_fn = trunc_map.get(group_by, TruncWeek)
        series_rows = (
            completed_trips
            .annotate(period=trunc_fn('pickup_date'))
            .values('period')
            .annotate(trips=Count('id'))
            .order_by('period')
        )
        result['series'] = [
            {
                'period': str(row['period']),
                'trips': row['trips'],
                'on_time_rate': None,  # per-period on-time rate requires heavier query
            }
            for row in series_rows
        ]

    return result


# Dashboard header and charts
def compute_dashboard_header(provider):
    from apps.trips.models import Trip
    today = timezone.now().date()

    active_trips = Trip.objects.filter(
        provider=provider,
        status__in=['in_route', 'active', 'awaiting_signature'],
    ).count()

    completed_today = Trip.objects.filter(
        provider=provider,
        status='completed',
        completed_at__date=today,
    ).count()

    revenue_today = Trip.objects.filter(
        provider=provider,
        status='completed',
        completed_at__date=today,
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

    cancellations_today = Trip.objects.filter(
        provider=provider,
        status='cancelled',
        cancelled_at__date=today,
    ).count()

    return {
        'active_trips': active_trips,
        'completed_today': completed_today,
        'revenue_today': str(revenue_today),
        'cancellations_today': cancellations_today,
    }


def compute_earnings_chart(provider, chart_range='week'):
    from apps.trips.models import Trip
    from django.db.models.functions import TruncDay

    today = timezone.now().date()
    days = 7 if chart_range == 'week' else 30
    start = today - timedelta(days=days - 1)

    rows = (
        Trip.objects.filter(
            provider=provider,
            status='completed',
            completed_at__date__gte=start,
            completed_at__date__lte=today,
        )
        .annotate(day=TruncDay('completed_at'))
        .values('day')
        .annotate(amount=Sum('total_amount'))
        .order_by('day')
    )

    # Fill in zero-amount days
    amounts_by_date = {
        row['day'].date(): str(row['amount'] or '0.00')
        for row in rows
    }
    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        series.append({'date': str(d), 'amount': amounts_by_date.get(d, '0.00')})

    return {'range': chart_range, 'series': series}


def compute_driver_status(provider):
    from apps.drivers.models import Driver

    # Map driver availability status to dashboard operational status
    STATUS_MAP = {
        'available': 'available',
        'on_trip': 'with_passenger',
        'break': 'offline',
        'off_duty': 'offline',
    }

    drivers = Driver.objects.filter(
        provider=provider,
        status_employment='active',
    ).select_related('vehicle').only(
        'id', 'full_name', 'profile_picture',
        'status_availability', 'vehicle',
    )

    counts = {'available': 0, 'en_route_to_pickup': 0, 'with_passenger': 0, 'offline': 0}
    driver_list = []

    for driver in drivers:
        # Determine operational status
        op_status = STATUS_MAP.get(driver.status_availability, 'offline')

        # Check if driver is en_route (trip status = in_route)
        if driver.status_availability == 'on_trip':
            try:
                from apps.trips.models import Trip
                has_in_route = Trip.objects.filter(
                    driver=driver, status='in_route'
                ).exists()
                if has_in_route:
                    op_status = 'en_route_to_pickup'
            except Exception:
                pass

        counts[op_status] = counts.get(op_status, 0) + 1
        driver_list.append({
            'driver_id': str(driver.id),
            'driver_name': driver.full_name,
            'driver_image': None,  # URL built in view with request context
            'operational_status': op_status,
            'assigned_vehicle_number': (
                driver.vehicle.license_plate if driver.vehicle else None
            ),
        })

    # Sort: available → en_route → with_passenger → offline
    order = {'available': 0, 'en_route_to_pickup': 1, 'with_passenger': 2, 'offline': 3}
    driver_list.sort(key=lambda d: order.get(d['operational_status'], 4))

    return {'overview': counts, 'drivers': driver_list}
