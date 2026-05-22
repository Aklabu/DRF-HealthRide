"""
Celery tasks for the compliance app.

scan_document_expiry   — runs daily, updates ComplianceDocument status + creates alerts
detect_missed_inspections — runs mid-morning daily, checks InspectionSchedule
"""
from django.utils import timezone
from datetime import timedelta


def scan_document_expiry():
    """
    Daily task: scan all active ComplianceDocument records, update
    days_until_expiration + status, create/suppress alerts, notify providers.
    """
    from .models import ComplianceDocument, ComplianceAlert
    from .utils import (
        compute_days_until_expiration,
        compute_document_status,
        compute_document_severity,
        invalidate_stats_cache,
        _build_document_alert_title,
        _build_document_alert_description,
    )

    now = timezone.now()
    today = now.date()
    notification_suppression_days = 7

    docs = ComplianceDocument.objects.filter(
        is_active=True,
        expiration_date__isnull=False,
    ).select_related('provider')

    processed = 0

    for doc in docs:
        days = compute_days_until_expiration(doc.expiration_date)
        status = compute_document_status(days)
        severity = compute_document_severity(days)

        # Update computed fields
        doc.days_until_expiration = days
        doc.status = status
        doc.last_checked_at = now
        doc.save(update_fields=['days_until_expiration', 'status', 'last_checked_at'])

        if not severity:
            processed += 1
            continue

        # Suppress duplicate notifications within 7 days
        if doc.notified_at:
            days_since_notified = (now - doc.notified_at).days
            if days_since_notified < notification_suppression_days:
                processed += 1
                continue

        # Create alert if no open alert already exists for this document
        existing_open = ComplianceAlert.objects.filter(
            related_document=doc,
            is_resolved=False,
        ).exists()

        if not existing_open:
            alert_type = 'document_expired' if days < 0 else 'document_expiring'
            ComplianceAlert.objects.create(
                provider=doc.provider,
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

        # Send notification — fire and forget
        try:
            from apps.notifications.utils import notify_document_expiry
            notify_document_expiry(doc)
            doc.notified_at = now
            doc.save(update_fields=['notified_at'])
        except Exception:
            pass

        invalidate_stats_cache(str(doc.provider.id))
        processed += 1

    return f'scan_document_expiry: processed {processed} documents'


def detect_missed_inspections():
    """
    Mid-morning daily task: check InspectionSchedule records for today
    where inspection_submitted = False and create missed inspection alerts.
    """
    from .models import InspectionSchedule, ComplianceAlert
    from .utils import invalidate_stats_cache

    today = timezone.now().date()

    missed = InspectionSchedule.objects.filter(
        expected_date=today,
        inspection_submitted=False,
        missed_alert_sent=False,
    ).select_related('provider', 'driver', 'vehicle')

    processed = 0

    for schedule in missed:
        ComplianceAlert.objects.create(
            provider=schedule.provider,
            alert_type='inspection_missed',
            severity='critical',
            title=f'Pre-Trip Inspection Missed — {schedule.driver.full_name}',
            description=(
                f'Driver {schedule.driver.full_name} has not submitted a pre-trip '
                f'inspection for vehicle {schedule.vehicle.license_plate} '
                f'as scheduled for {today}.'
            ),
            holder_type='driver',
            holder_id=schedule.driver.id,
            holder_name=schedule.driver.full_name,
            due_date=today,
        )

        schedule.missed_alert_sent = True
        schedule.save(update_fields=['missed_alert_sent'])

        # Notify provider
        try:
            from apps.notifications.utils import notify_missed_inspection
            notify_missed_inspection(schedule)
        except Exception:
            pass

        invalidate_stats_cache(str(schedule.provider.id))
        processed += 1

    return f'detect_missed_inspections: processed {processed} missed schedules'


# Celery task registration — allows these functions to be called asynchronously
try:
    from config.celery import app as celery_app

    scan_document_expiry = celery_app.task(
        name='compliance.scan_document_expiry',
        ignore_result=False,
    )(scan_document_expiry)

    detect_missed_inspections = celery_app.task(
        name='compliance.detect_missed_inspections',
        ignore_result=False,
    )(detect_missed_inspections)

except Exception:
    pass
