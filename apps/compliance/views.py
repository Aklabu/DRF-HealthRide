from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q, Count, Case, When, IntegerField
from django.utils import timezone
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .models import (
    PreTripInspection, ComplianceDocument, ComplianceAlert, InspectionSchedule,
)
from .serializers import (
    InspectionListSerializer,
    InspectionDetailSerializer,
    InspectionCreateSerializer,
    InspectionPatchSerializer,
    ComplianceDocumentListSerializer,
    ComplianceDocumentDetailSerializer,
    ComplianceDocumentCreateSerializer,
    ComplianceDocumentUpdateSerializer,
    ComplianceAlertListSerializer,
    ComplianceAlertDetailSerializer,
)
from .utils import (
    compute_days_until_expiration,
    compute_document_status,
    compute_document_severity,
    register_compliance_document,
    invalidate_stats_cache,
    get_cached_stats,
    set_cached_stats,
    _build_document_alert_title,
    _build_document_alert_description,
)


# Stats view — provides aggregated counts for dashboard and reports
class ComplianceStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        provider_id = str(request.user.id)

        # Try cache first
        cached = get_cached_stats(provider_id)
        if cached:
            return CustomResponse.success(
                message='Compliance stats fetched.',
                data=cached,
                status_code=200
            )

        today = timezone.now().date()

        # Document counts by status
        doc_counts = ComplianceDocument.objects.filter(
            provider=request.user, is_active=True
        ).values('status').annotate(count=Count('id'))
        doc_map = {item['status']: item['count'] for item in doc_counts}

        # Alert counts by severity (unresolved only)
        alert_counts = ComplianceAlert.objects.filter(
            provider=request.user, is_resolved=False
        ).values('severity').annotate(count=Count('id'))
        alert_map = {item['severity']: item['count'] for item in alert_counts}

        # Inspections today
        submitted_today = PreTripInspection.objects.filter(
            provider=request.user,
            date_time__date=today,
        ).count()

        missed_today = InspectionSchedule.objects.filter(
            provider=request.user,
            expected_date=today,
            inspection_submitted=False,
        ).count()

        data = {
            'documents': {
                'valid': doc_map.get('valid', 0),
                'expiring_soon': doc_map.get('expiring_soon', 0),
                'expired': doc_map.get('expired', 0),
            },
            'alerts': {
                'critical': alert_map.get('critical', 0),
                'warning': alert_map.get('warning', 0),
                'info': alert_map.get('info', 0),
            },
            'inspections_today': {
                'submitted': submitted_today,
                'missed': missed_today,
            },
        }

        set_cached_stats(provider_id, data)

        return CustomResponse.success(
            message='Compliance stats fetched.',
            data=data,
            status_code=200
        )


# PreTripInspection views — list, detail, create, patch
class InspectionListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        qs = PreTripInspection.objects.filter(
            provider=request.user
        ).select_related('driver', 'vehicle')

        # Filters
        driver_id = request.query_params.get('driver_id')
        if driver_id:
            qs = qs.filter(driver__id=driver_id)

        vehicle_id = request.query_params.get('vehicle_id')
        if vehicle_id:
            qs = qs.filter(vehicle__id=vehicle_id)

        date_filter = request.query_params.get('date')
        if date_filter:
            qs = qs.filter(date_time__date=date_filter)

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        search = request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(driver__full_name__icontains=search) |
                Q(vehicle__license_plate__icontains=search)
            )

        serializer = InspectionListSerializer(qs, many=True)
        return CustomResponse.success(
            message='Inspections fetched.',
            data=serializer.data,
            status_code=200
        )

    def post(self, request):
        serializer = InspectionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate driver and vehicle belong to this provider
        from apps.drivers.models import Driver
        from apps.vehicles.models import Vehicle

        try:
            driver = Driver.objects.get(id=data['driver'], provider=request.user)
        except Driver.DoesNotExist:
            return CustomResponse.error(
                message='Driver not found or does not belong to your account.',
                status_code=404
            )

        try:
            vehicle = Vehicle.objects.get(id=data['vehicle'], provider=request.user)
        except Vehicle.DoesNotExist:
            return CustomResponse.error(
                message='Vehicle not found or does not belong to your account.',
                status_code=404
            )

        # Determine status from checklist
        checklist_fields = [
            'vehicle_exterior', 'vehicle_interior', 'tires', 'brakes',
            'fluids', 'lights', 'safety_equipment', 'cleanliness',
            'dashboard_warning_lights',
        ]
        has_failure = any(data.get(f) == 'fail' for f in checklist_fields)
        if data.get('wheelchair_ramp') == 'fail':
            has_failure = True

        status = 'issues_found' if has_failure else 'all_clear'

        with transaction.atomic():
            inspection = PreTripInspection.objects.create(
                provider=request.user,
                driver=driver,
                vehicle=vehicle,
                date_time=timezone.now(),
                odometer=data['odometer'],
                fuel_level=data['fuel_level'],
                status=status,
                vehicle_exterior=data['vehicle_exterior'],
                vehicle_interior=data['vehicle_interior'],
                tires=data['tires'],
                brakes=data['brakes'],
                fluids=data['fluids'],
                lights=data['lights'],
                safety_equipment=data['safety_equipment'],
                cleanliness=data['cleanliness'],
                wheelchair_ramp=data.get('wheelchair_ramp', 'not_applicable'),
                dashboard_warning_lights=data['dashboard_warning_lights'],
                issue_description=data.get('issue_description'),
                issue_photo=data.get('issue_photo'),
                signature=data['signature'],
            )

            # Link to InspectionSchedule if one exists for today
            today = timezone.now().date()
            try:
                schedule = InspectionSchedule.objects.get(
                    provider=request.user,
                    driver=driver,
                    vehicle=vehicle,
                    expected_date=today,
                )
                schedule.inspection_submitted = True
                schedule.inspection = inspection
                schedule.save(update_fields=['inspection_submitted', 'inspection'])
            except InspectionSchedule.DoesNotExist:
                pass

            # Create alert if issues found
            if status == 'issues_found':
                severity = 'critical' if inspection.has_critical_failure() else 'warning'
                failed_items = [
                    f for f in checklist_fields if data.get(f) == 'fail'
                ]
                if data.get('wheelchair_ramp') == 'fail':
                    failed_items.append('wheelchair_ramp')

                ComplianceAlert.objects.create(
                    provider=request.user,
                    alert_type='inspection_failed',
                    severity=severity,
                    title=f'Pre-Trip Inspection Failed — {driver.full_name}',
                    description=(
                        f'Driver {driver.full_name} reported issues on vehicle '
                        f'{vehicle.license_plate}. Failed items: '
                        f'{", ".join(failed_items)}. '
                        f'Notes: {data.get("issue_description", "")}'
                    ),
                    holder_type='driver',
                    holder_id=driver.id,
                    holder_name=driver.full_name,
                    related_inspection=inspection,
                    due_date=today,
                )

                # Notify provider
                try:
                    from apps.notifications.utils import notify_inspection_failed
                    notify_inspection_failed(inspection)
                except Exception:
                    pass

        invalidate_stats_cache(str(request.user.id))

        response_serializer = InspectionDetailSerializer(inspection, context={'request': request})
        return CustomResponse.success(
            message='Inspection submitted.',
            data=response_serializer.data,
            status_code=201
        )


# Detail and patch view for PreTripInspection
class InspectionDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, id):
        inspection = get_object_or_404(PreTripInspection, id=id, provider=request.user)
        serializer = InspectionDetailSerializer(inspection, context={'request': request})
        return CustomResponse.success(
            message='Inspection fetched.',
            data=serializer.data,
            status_code=200
        )

    def patch(self, request, id):
        inspection = get_object_or_404(PreTripInspection, id=id, provider=request.user)

        # Only issue_description and issue_photo are editable after submission
        serializer = InspectionPatchSerializer(inspection, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()

        return CustomResponse.success(
            message='Inspection updated.',
            data=InspectionDetailSerializer(inspection, context={'request': request}).data,
            status_code=200
        )


# ComplianceDocument views — list, detail, create (internal), patch, delete
class ComplianceDocumentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = ComplianceDocument.objects.filter(
            provider=request.user, is_active=True
        )

        holder_type = request.query_params.get('holder_type')
        if holder_type:
            qs = qs.filter(holder_type=holder_type)

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        doc_type = request.query_params.get('document_type')
        if doc_type:
            qs = qs.filter(document_type=doc_type)

        search = request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(holder_name__icontains=search) |
                Q(document_number__icontains=search)
            )

        # Most urgent first — expired (negative days) sort before expiring
        qs = qs.order_by(
            Case(
                When(days_until_expiration__isnull=True, then=9999),
                default='days_until_expiration',
                output_field=IntegerField(),
            )
        )

        serializer = ComplianceDocumentListSerializer(qs, many=True)
        return CustomResponse.success(
            message='Compliance documents fetched.',
            data=serializer.data,
            status_code=200
        )

    def post(self, request):
        """Internal service call — called by drivers/vehicles apps."""
        serializer = ComplianceDocumentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        doc = register_compliance_document(
            provider=request.user,
            holder_type=data['holder_type'],
            holder_id=data['holder_id'],
            holder_name=data['holder_name'],
            document_type=data['document_type'],
            document_number=data.get('document_number'),
            upload_date=data['upload_date'],
            expiration_date=data.get('expiration_date'),
            file_reference=data.get('file_reference', ''),
        )

        response_serializer = ComplianceDocumentDetailSerializer(doc)
        return CustomResponse.success(
            message='Compliance document registered.',
            data=response_serializer.data,
            status_code=201
        )


class ComplianceDocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        doc = get_object_or_404(
            ComplianceDocument, id=id, provider=request.user, is_active=True
        )
        serializer = ComplianceDocumentDetailSerializer(doc)
        return CustomResponse.success(
            message='Document fetched.',
            data=serializer.data,
            status_code=200
        )

    def patch(self, request, id):
        """Document renewal — called by drivers/vehicles apps."""
        doc = get_object_or_404(
            ComplianceDocument, id=id, provider=request.user, is_active=True
        )

        serializer = ComplianceDocumentUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        now = timezone.now()

        with transaction.atomic():
            # Apply updates
            for field, value in data.items():
                setattr(doc, field, value)

            # Recompute status
            days = compute_days_until_expiration(doc.expiration_date)
            doc.days_until_expiration = days
            doc.status = compute_document_status(days)
            doc.last_checked_at = now
            doc.notified_at = None  # reset so renewal notification can fire
            doc.save()

            # Resolve existing open alerts for this document
            ComplianceAlert.objects.filter(
                related_document=doc, is_resolved=False
            ).update(is_resolved=True, resolved_at=now)

            # Create fresh alert if still within threshold
            severity = compute_document_severity(days)
            if severity:
                alert_type = 'document_expired' if (days is not None and days < 0) else 'document_expiring'
                ComplianceAlert.objects.create(
                    provider=request.user,
                    alert_type=alert_type,
                    severity=severity,
                    title=_build_document_alert_title(doc.document_type, doc.holder_name, days),
                    description=_build_document_alert_description(
                        doc.document_type, doc.holder_name, days, doc.expiration_date
                    ),
                    holder_type=doc.holder_type,
                    holder_id=doc.holder_id,
                    holder_name=doc.holder_name,
                    related_document=doc,
                    days_remaining=days,
                    due_date=doc.expiration_date,
                )

        invalidate_stats_cache(str(request.user.id))

        response_serializer = ComplianceDocumentDetailSerializer(doc)
        return CustomResponse.success(
            message='Document updated.',
            data=response_serializer.data,
            status_code=200
        )

    def delete(self, request, id):
        doc = get_object_or_404(
            ComplianceDocument, id=id, provider=request.user, is_active=True
        )

        with transaction.atomic():
            doc.is_active = False
            doc.save(update_fields=['is_active'])

            # Resolve open alerts
            ComplianceAlert.objects.filter(
                related_document=doc, is_resolved=False
            ).update(is_resolved=True, resolved_at=timezone.now())

        invalidate_stats_cache(str(request.user.id))
        return Response(status=204)


# ComplianceAlert views — list, detail, resolve
class ComplianceAlertListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = ComplianceAlert.objects.filter(provider=request.user)

        severity_filter = request.query_params.get('severity')
        if severity_filter:
            qs = qs.filter(severity=severity_filter)

        holder_type = request.query_params.get('holder_type')
        if holder_type:
            qs = qs.filter(holder_type=holder_type)

        # Default: unresolved only
        is_resolved = request.query_params.get('is_resolved', 'false').lower()
        if is_resolved == 'true':
            qs = qs.filter(is_resolved=True)
        else:
            qs = qs.filter(is_resolved=False)

        serializer = ComplianceAlertListSerializer(qs, many=True)
        return CustomResponse.success(
            message='Alerts fetched.',
            data=serializer.data,
            status_code=200
        )


class ComplianceAlertDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        alert = get_object_or_404(ComplianceAlert, id=id, provider=request.user)
        serializer = ComplianceAlertDetailSerializer(alert)
        return CustomResponse.success(
            message='Alert fetched.',
            data=serializer.data,
            status_code=200
        )


class ComplianceAlertResolveView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        alert = get_object_or_404(ComplianceAlert, id=id, provider=request.user)

        if alert.is_resolved:
            return CustomResponse.error(
                message='Alert is already resolved.',
                status_code=400
            )

        alert.is_resolved = True
        alert.resolved_at = timezone.now()
        alert.save(update_fields=['is_resolved', 'resolved_at'])

        invalidate_stats_cache(str(request.user.id))

        serializer = ComplianceAlertDetailSerializer(alert)
        return CustomResponse.success(
            message='Alert resolved.',
            data=serializer.data,
            status_code=200
        )
    

# Additional views for reports and summaries
class DocumentSummaryReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count

        docs = ComplianceDocument.objects.filter(
            provider=request.user, is_active=True
        ).values('holder_id', 'holder_name', 'holder_type', 'status').annotate(
            count=Count('id')
        )

        # Aggregate per holder
        holders = {}
        for row in docs:
            key = str(row['holder_id'])
            if key not in holders:
                holders[key] = {
                    'holder_name': row['holder_name'],
                    'holder_type': row['holder_type'],
                    'total_documents': 0,
                    'valid': 0,
                    'expiring_soon': 0,
                    'expired': 0,
                }
            holders[key]['total_documents'] += row['count']
            holders[key][row['status']] = holders[key].get(row['status'], 0) + row['count']

        # Sort: most expired first, then most expiring
        summary = sorted(
            holders.values(),
            key=lambda h: (-h['expired'], -h['expiring_soon'])
        )

        return CustomResponse.success(
            message='Document summary report fetched.',
            data={'summary': summary},
            status_code=200
        )


# InspectionSummaryReportView — aggregated inspection counts per driver for a given month
class InspectionSummaryReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count

        # Optional month filter — defaults to current month
        today = timezone.now().date()
        month_start = today.replace(day=1)
        month_param = request.query_params.get('month')  # format: YYYY-MM
        if month_param:
            try:
                from datetime import datetime
                month_start = datetime.strptime(month_param, '%Y-%m').date()
            except ValueError:
                return CustomResponse.error(
                    message='Invalid month format. Use YYYY-MM.',
                    status_code=400
                )

        # Next month start for range end
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)

        # Aggregate inspections per driver
        inspections = PreTripInspection.objects.filter(
            provider=request.user,
            date_time__date__gte=month_start,
            date_time__date__lt=month_end,
        ).values('driver__id', 'driver__full_name', 'status').annotate(count=Count('id'))

        drivers = {}
        for row in inspections:
            driver_id = str(row['driver__id'])
            if driver_id not in drivers:
                drivers[driver_id] = {
                    'driver_id': driver_id,
                    'driver_name': row['driver__full_name'],
                    'total_inspections': 0,
                    'all_clear': 0,
                    'issues_found': 0,
                    'missed': 0,
                }
            drivers[driver_id]['total_inspections'] += row['count']
            drivers[driver_id][row['status']] = (
                drivers[driver_id].get(row['status'], 0) + row['count']
            )

        # Add missed inspection counts from InspectionSchedule
        missed_qs = InspectionSchedule.objects.filter(
            provider=request.user,
            expected_date__gte=month_start,
            expected_date__lt=month_end,
            inspection_submitted=False,
        ).values('driver__id', 'driver__full_name').annotate(missed=Count('id'))

        for row in missed_qs:
            driver_id = str(row['driver__id'])
            if driver_id not in drivers:
                drivers[driver_id] = {
                    'driver_id': driver_id,
                    'driver_name': row['driver__full_name'],
                    'total_inspections': 0,
                    'all_clear': 0,
                    'issues_found': 0,
                    'missed': 0,
                }
            drivers[driver_id]['missed'] += row['missed']

        summary = sorted(
            drivers.values(),
            key=lambda d: -d['missed']
        )

        return CustomResponse.success(
            message='Inspection summary report fetched.',
            data={'summary': summary},
            status_code=200
        )
