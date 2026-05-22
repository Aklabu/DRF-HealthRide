from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum, Count, Q

from utils.response import CustomResponse
from .models import ReportSnapshot, DashboardCache
from .serializers import (
    TripVolumeQuerySerializer,
    DriverHoursQuerySerializer,
    PassengerServiceQuerySerializer,
    DashboardQuerySerializer,
)
from .utils import (
    get_valid_snapshot,
    upsert_snapshot,
    get_dashboard_expires_at,
    compute_trip_volume,
    compute_driver_hours,
    compute_passenger_service,
    compute_dashboard_header,
    compute_earnings_chart,
    compute_driver_status,
)

BOOKING_PAGE_SIZE = 20


# Trip Volume, Driver Hours, Passenger Service reports
class TripVolumeReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = TripVolumeQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        start = data['date_range_start']
        end = data['date_range_end']
        group_by = data.get('group_by')

        # Check snapshot cache (only when no group_by or group_by is consistent)
        snap = get_valid_snapshot(request.user, 'trip_volume', start, end)
        if snap and not group_by:
            return CustomResponse.success(
                message='Trip volume report fetched (cached).',
                data=snap.data,
                status_code=200
            )

        result = compute_trip_volume(request.user, start, end, group_by=group_by)

        # Cache only non-grouped totals
        if not group_by:
            upsert_snapshot(request.user, 'trip_volume', start, end, result)

        return CustomResponse.success(
            message='Trip volume report fetched.',
            data=result,
            status_code=200
        )


class DriverHoursReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = DriverHoursQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        start = data['date_range_start']
        end = data['date_range_end']
        group_by = data.get('group_by')
        driver_id = data.get('driver_id')

        # Validate driver belongs to provider if specified
        if driver_id:
            from apps.drivers.models import Driver
            if not Driver.objects.filter(id=driver_id, provider=request.user).exists():
                return CustomResponse.error(
                    message='Driver not found or does not belong to your account.',
                    status_code=404
                )

        # Skip snapshot cache for driver-specific queries
        if not driver_id and not group_by:
            snap = get_valid_snapshot(request.user, 'driver_hours', start, end)
            if snap:
                return CustomResponse.success(
                    message='Driver hours report fetched (cached).',
                    data=snap.data,
                    status_code=200
                )

        result = compute_driver_hours(
            request.user, start, end, group_by=group_by, driver_id=driver_id
        )

        if not driver_id and not group_by:
            upsert_snapshot(request.user, 'driver_hours', start, end, result)

        return CustomResponse.success(
            message='Driver hours report fetched.',
            data=result,
            status_code=200
        )


class PassengerServiceReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = PassengerServiceQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        start = data['date_range_start']
        end = data['date_range_end']
        group_by = data.get('group_by')

        if not group_by:
            snap = get_valid_snapshot(request.user, 'passenger_service', start, end)
            if snap:
                return CustomResponse.success(
                    message='Passenger service report fetched (cached).',
                    data=snap.data,
                    status_code=200
                )

        result = compute_passenger_service(request.user, start, end, group_by=group_by)

        if not group_by:
            upsert_snapshot(request.user, 'passenger_service', start, end, result)

        return CustomResponse.success(
            message='Passenger service report fetched.',
            data=result,
            status_code=200
        )


# Dashboard and related views
class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = DashboardQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        params = serializer.validated_data
        booking_page = params.get('booking_page', 1)
        chart_range = params.get('chart_range', 'week')

        # Try dashboard cache for header, chart, driver status
        header_data = None
        earnings_chart_data = None
        driver_status_data = None

        try:
            cache = request.user.dashboard_cache
            if cache.is_valid():
                header_data = cache.header_data
                earnings_chart_data = cache.earnings_chart_data
                driver_status_data = cache.driver_status_data
        except DashboardCache.DoesNotExist:
            pass

        # Recompute if cache miss
        if not header_data:
            header_data = compute_dashboard_header(request.user)
            earnings_chart_data = compute_earnings_chart(request.user, chart_range)
            driver_status_data = compute_driver_status(request.user)

            now = timezone.now()
            DashboardCache.objects.update_or_create(
                provider=request.user,
                defaults={
                    'header_data': header_data,
                    'earnings_chart_data': earnings_chart_data,
                    'driver_status_data': driver_status_data,
                    'generated_at': now,
                    'expires_at': get_dashboard_expires_at(),
                }
            )

        # Booking list — always live, paginated
        bookings_data = self._get_bookings(request.user, booking_page)

        return CustomResponse.success(
            message='Dashboard fetched.',
            data={
                'header': header_data,
                'earnings_chart': earnings_chart_data,
                'driver_status': driver_status_data,
                'bookings': bookings_data,
            },
            status_code=200
        )

    def _get_bookings(self, provider, page):
        from apps.trips.models import Trip

        qs = Trip.objects.filter(
            provider=provider,
            parent_trip__isnull=True,
        ).select_related(
            'passenger', 'vehicle'
        ).prefetch_related('passenger_contacts').order_by('-pickup_date', '-pickup_time')

        total = qs.count()
        offset = (page - 1) * BOOKING_PAGE_SIZE
        trips = qs[offset: offset + BOOKING_PAGE_SIZE]

        results = []
        for trip in trips:
            passenger_name = ''
            if trip.passenger:
                passenger_name = trip.passenger.full_name
            else:
                contact = trip.passenger_contacts.first()
                if contact:
                    passenger_name = contact.full_name

            results.append({
                'booking_id': str(trip.id),
                'date': str(trip.pickup_date),
                'passenger_name': passenger_name,
                'vehicle_type': trip.vehicle.vehicle_type if trip.vehicle else None,
                'plan': trip.trip_type,
                'pickup_date': str(trip.pickup_date),
                'return_date': None,  # round-trip support in future
                'payment_status': trip.payment_status,
                'trip_status': trip.status,
            })

        total_pages = (total + BOOKING_PAGE_SIZE - 1) // BOOKING_PAGE_SIZE
        return {
            'count': total,
            'next': page + 1 if page < total_pages else None,
            'previous': page - 1 if page > 1 else None,
            'results': results,
        }


class ActiveTripsView(APIView):
    # Always live — never cached. Active trip progress changes continuously
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.trips.models import Trip
        from datetime import datetime

        qs = Trip.objects.filter(
            provider=request.user,
            status__in=['in_route', 'active', 'awaiting_signature'],
        ).select_related('passenger', 'driver', 'vehicle').prefetch_related(
            'passenger_contacts'
        ).order_by('started_at')

        now = timezone.now()
        active_trips = []

        for trip in qs:
            passenger_name = ''
            if trip.passenger:
                passenger_name = trip.passenger.full_name
            else:
                contact = trip.passenger_contacts.first()
                if contact:
                    passenger_name = contact.full_name

            # Compute progress — capped at 99% until status = completed
            progress = 0
            if trip.started_at and trip.estimated_duration > 0:
                elapsed = (now - trip.started_at).total_seconds()
                total = trip.estimated_duration * 60
                progress = min(99, int((elapsed / total) * 100))

            active_trips.append({
                'trip_id': str(trip.id),
                'passenger_name': passenger_name,
                'driver_name': trip.driver.full_name if trip.driver else None,
                'scheduled_time': str(trip.pickup_time),
                'trip_type': trip.trip_type,
                'pickup_location': trip.pickup_address,
                'dropoff_location': trip.dropoff_address,
                'status': trip.status,
                'trip_progress': progress,
            })

        return CustomResponse.success(
            message='Active trips fetched.',
            data={'active_trips': active_trips},
            status_code=200
        )


class ComplianceAlertsView(APIView):
    # Always live — compliance alerts must reflect current state
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.compliance.models import ComplianceAlert

        alerts_qs = ComplianceAlert.objects.filter(
            provider=request.user,
            is_resolved=False,
        ).order_by(
            # critical=0, warning=1, info=2
            'severity',
            'days_remaining',
            '-created_at',
        )

        counts = {'critical': 0, 'warning': 0, 'info': 0}
        alerts = []

        for alert in alerts_qs:
            counts[alert.severity] = counts.get(alert.severity, 0) + 1
            alerts.append({
                'severity': alert.severity,
                'holder_name': alert.holder_name,
                'holder_type': alert.holder_type,
                'alert_type': alert.alert_type,
                'title': alert.title,
                'days_remaining': alert.days_remaining,
                'due_date': str(alert.due_date) if alert.due_date else None,
                'status': 'unresolved',
            })

        return CustomResponse.success(
            message='Compliance alerts fetched.',
            data={'counts': counts, 'alerts': alerts},
            status_code=200
        )


class DriverStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Try dashboard cache driver_status_data
        try:
            cache = request.user.dashboard_cache
            if cache.is_valid() and cache.driver_status_data:
                return CustomResponse.success(
                    message='Driver status fetched (cached).',
                    data=cache.driver_status_data,
                    status_code=200
                )
        except DashboardCache.DoesNotExist:
            pass

        result = compute_driver_status(request.user)

        # Attach profile picture URLs
        for driver_item in result.get('drivers', []):
            from apps.drivers.models import Driver
            try:
                d = Driver.objects.get(id=driver_item['driver_id'])
                if d.profile_picture:
                    driver_item['driver_image'] = request.build_absolute_uri(
                        d.profile_picture.url
                    )
            except Exception:
                pass

        # Write back to dashboard cache
        now = timezone.now()
        DashboardCache.objects.update_or_create(
            provider=request.user,
            defaults={
                'driver_status_data': result,
                'generated_at': now,
                'expires_at': get_dashboard_expires_at(),
            }
        )

        return CustomResponse.success(
            message='Driver status fetched.',
            data=result,
            status_code=200
        )
