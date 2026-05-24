"""
Internal notification trigger service.

Called directly by other apps (trips, compliance, billing, scheduling, driver_app).
Not an HTTP endpoint — direct function call within the same Django project.
"""
import re
from django.utils import timezone


# Supported template placeholders
SUPPORTED_PLACEHOLDERS = {
    'driver_name', 'trip_id', 'due_date', 'amount',
    'passenger_name', 'vehicle_number', 'facility_name',
    'invoice_number', 'document_type', 'days_remaining',
}

# Unread count cache key per recipient
def _unread_cache_key(recipient_type, recipient_id):
    return f'unread_count_{recipient_type}_{recipient_id}'


def invalidate_unread_cache(recipient_type, recipient_id):
    from django.core.cache import cache
    cache.delete(_unread_cache_key(recipient_type, str(recipient_id)))


def get_cached_unread_count(recipient_type, recipient_id):
    from django.core.cache import cache
    return cache.get(_unread_cache_key(recipient_type, str(recipient_id)))


def set_cached_unread_count(recipient_type, recipient_id, count):
    from django.core.cache import cache
    cache.set(_unread_cache_key(recipient_type, str(recipient_id)), count, timeout=300)


def validate_placeholders(content):
    """
    Extract all {{placeholder}} names from content and validate against
    SUPPORTED_PLACEHOLDERS. Returns list of unsupported names (empty = valid).
    """
    found = re.findall(r'\{\{(\w+)\}\}', content)
    return [name for name in found if name not in SUPPORTED_PLACEHOLDERS]


def get_or_create_preference(recipient_type, recipient_id, provider):
    # Fetch or auto-create NotificationPreference with defaults.
    from .models import NotificationPreference
    pref, _ = NotificationPreference.objects.get_or_create(
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        defaults={'provider': provider},
    )
    return pref


# Core send function 
def send_notification(
    recipient_type,
    recipient_id,
    provider_id,
    title,
    message,
    category,
    related_object_type=None,
    related_object_id=None,
):
    """
    Internal notification trigger — called by other apps on system events.

    Steps:
    1. Fetch preference — abort if category disabled
    2. Create Notification record
    3. Dispatch channel tasks (push, email, SMS) via Celery
    4. Invalidate unread count cache
    """
    from .models import NotificationPreference, Notification
    from apps.accounts.models import Provider

    try:
        provider = Provider.objects.get(id=provider_id)
    except Provider.DoesNotExist:
        return None

    # Step 1 — Check preference
    try:
        pref = NotificationPreference.objects.get(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
        )
    except NotificationPreference.DoesNotExist:
        # Auto-create with defaults
        pref = NotificationPreference.objects.create(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            provider=provider,
        )

    if not pref.is_category_enabled(category):
        return None  # Category disabled — no record created

    # Step 2 — Create Notification record
    notification = Notification.objects.create(
        provider=provider,
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        title=title,
        message=message,
        category=category,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
    )

    # Step 3 — Dispatch channel tasks
    _dispatch_channels(notification, pref)

    # Step 4 — Invalidate unread count cache
    invalidate_unread_cache(recipient_type, recipient_id)

    return notification


def _dispatch_channels(notification, pref):
    # Dispatch push, email, SMS tasks via Celery — fire and forget.
    from .tasks import send_push_notification, send_email_notification, send_sms_notification

    if pref.push_enabled:
        try:
            send_push_notification.delay(str(notification.id))
        except Exception:
            pass

    if pref.email_enabled:
        try:
            send_email_notification.delay(str(notification.id))
        except Exception:
            pass

    if pref.sms_enabled:
        try:
            send_sms_notification.delay(str(notification.id))
        except Exception:
            pass


# Convenience wrappers called by other apps 
def notify_driver_assignment(trip, driver):
    send_notification(
        recipient_type='driver',
        recipient_id=str(driver.id),
        provider_id=str(trip.provider.id),
        title='New Trip Assigned',
        message=f'You have been assigned trip {trip.trip_number}. Pickup at {trip.pickup_address}.',
        category='trip',
        related_object_type='trip',
        related_object_id=str(trip.id),
    )


def notify_driver_unassignment(trip, driver):
    send_notification(
        recipient_type='driver',
        recipient_id=str(driver.id),
        provider_id=str(trip.provider.id),
        title='Trip Unassigned',
        message=f'You have been removed from trip {trip.trip_number}.',
        category='trip',
        related_object_type='trip',
        related_object_id=str(trip.id),
    )


def notify_signature_required(trip):
    if trip.driver:
        send_notification(
            recipient_type='driver',
            recipient_id=str(trip.driver.id),
            provider_id=str(trip.provider.id),
            title='Signature Required',
            message=f'Trip {trip.trip_number} is awaiting passenger signature.',
            category='trip',
            related_object_type='trip',
            related_object_id=str(trip.id),
        )


def notify_document_expiry(document):
    send_notification(
        recipient_type='provider',
        recipient_id=str(document.provider.id),
        provider_id=str(document.provider.id),
        title=f'Document Expiring — {document.holder_name}',
        message=(
            f'{document.document_type.replace("_", " ").title()} for '
            f'{document.holder_name} expires on {document.expiration_date} '
            f'({document.days_until_expiration} days remaining).'
        ),
        category='compliance',
        related_object_type='compliance_document',
        related_object_id=str(document.id),
    )


def notify_missed_inspection(schedule):
    send_notification(
        recipient_type='provider',
        recipient_id=str(schedule.provider.id),
        provider_id=str(schedule.provider.id),
        title=f'Missed Inspection — {schedule.driver.full_name}',
        message=(
            f'Driver {schedule.driver.full_name} has not submitted a pre-trip '
            f'inspection for vehicle {schedule.vehicle.license_plate} today.'
        ),
        category='compliance',
        related_object_type='inspection_schedule',
        related_object_id=str(schedule.id),
    )


def notify_inspection_failed(inspection):
    send_notification(
        recipient_type='provider',
        recipient_id=str(inspection.provider.id),
        provider_id=str(inspection.provider.id),
        title=f'Inspection Failed — {inspection.driver.full_name if inspection.driver else "Unknown"}',
        message=(
            f'Pre-trip inspection for vehicle '
            f'{inspection.vehicle.license_plate if inspection.vehicle else "Unknown"} '
            f'reported issues. Notes: {inspection.issue_description or "None"}'
        ),
        category='compliance',
        related_object_type='pre_trip_inspection',
        related_object_id=str(inspection.id),
    )


def notify_invoice_overdue(invoice):
    send_notification(
        recipient_type='provider',
        recipient_id=str(invoice.provider.id),
        provider_id=str(invoice.provider.id),
        title=f'Invoice Overdue — {invoice.invoice_number}',
        message=(
            f'Invoice {invoice.invoice_number} for '
            f'{invoice.facility.facility_name if invoice.facility else "direct billing"} '
            f'is overdue. Amount: ${invoice.amount}.'
        ),
        category='payment',
        related_object_type='invoice',
        related_object_id=str(invoice.id),
    )


def notify_payment_failed(invoice):
    send_notification(
        recipient_type='provider',
        recipient_id=str(invoice.provider.id),
        provider_id=str(invoice.provider.id),
        title=f'Payment Failed — {invoice.invoice_number}',
        message=(
            f'Payment for invoice {invoice.invoice_number} failed. '
            f'Please check your Stripe account.'
        ),
        category='payment',
        related_object_type='invoice',
        related_object_id=str(invoice.id),
    )
