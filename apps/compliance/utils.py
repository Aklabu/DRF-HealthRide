"""
Shared compliance utility functions.

These are called directly by other apps (drivers, vehicles) as internal
service calls — not via HTTP — keeping operations transactional and fast.
"""
from django.utils import timezone


# Several helper functions to compute document status and alert severity based on expiration dates.
def compute_document_status(days_until_expiration):
    # Compute document status from days_until_expiration.
    if days_until_expiration is None:
        return 'valid'
    if days_until_expiration < 0:
        return 'expired'
    if days_until_expiration <= 60:
        return 'expiring_soon'
    return 'valid'


def compute_document_severity(days_until_expiration):
    # Compute alert severity from days_until_expiration.
    if days_until_expiration is None:
        return None
    if days_until_expiration <= 7:
        return 'critical'
    if days_until_expiration <= 30:
        return 'warning'
    if days_until_expiration <= 60:
        return 'info'
    return None  # No alert needed


def compute_days_until_expiration(expiration_date):
    # Compute days until expiration from expiration_date.
    if not expiration_date:
        return None
    today = timezone.now().date()
    return (expiration_date - today).days


# Cache keys and helper functions for compliance stats caching
STATS_CACHE_TIMEOUT = 300  # 5 minutes


def get_stats_cache_key(provider_id):
    return f'compliance_stats_{provider_id}'


def invalidate_stats_cache(provider_id):
    # Invalidate cached stats for a provider when relevant data changes.
    from django.core.cache import cache
    cache.delete(get_stats_cache_key(provider_id))


def get_cached_stats(provider_id):
    from django.core.cache import cache
    return cache.get(get_stats_cache_key(provider_id))


def set_cached_stats(provider_id, data):
    from django.core.cache import cache
    cache.set(get_stats_cache_key(provider_id), data, timeout=STATS_CACHE_TIMEOUT)


# Internal service call — register document from drivers/vehicles app 
def register_compliance_document(
    provider,
    holder_type,
    holder_id,
    holder_name,
    document_type,
    document_number,
    upload_date,
    expiration_date,
    file_reference='',
):
    """
    Called by drivers app and vehicles app when a document is uploaded.
    Creates or updates a ComplianceDocument record and triggers alerts.
    Returns the ComplianceDocument instance.
    """
    from .models import ComplianceDocument, ComplianceAlert

    days = compute_days_until_expiration(expiration_date)
    status = compute_document_status(days)
    now = timezone.now()

    doc, created = ComplianceDocument.objects.update_or_create(
        provider=provider,
        holder_type=holder_type,
        holder_id=holder_id,
        document_type=document_type,
        is_active=True,
        defaults={
            'holder_name': holder_name,
            'document_number': document_number,
            'upload_date': upload_date,
            'expiration_date': expiration_date,
            'file_reference': file_reference,
            'status': status,
            'days_until_expiration': days,
            'last_checked_at': now,
            'notified_at': None,  # reset so renewal notification can fire
        }
    )

    # Resolve any existing open alerts for this document on renewal
    if not created:
        ComplianceAlert.objects.filter(
            related_document=doc,
            is_resolved=False,
        ).update(is_resolved=True, resolved_at=now)

    # Create alert immediately if expiring or expired
    severity = compute_document_severity(days)
    if severity:
        alert_type = 'document_expired' if (days is not None and days < 0) else 'document_expiring'
        title = _build_document_alert_title(document_type, holder_name, days)
        description = _build_document_alert_description(document_type, holder_name, days, expiration_date)

        ComplianceAlert.objects.create(
            provider=provider,
            alert_type=alert_type,
            severity=severity,
            title=title,
            description=description,
            holder_type=holder_type,
            holder_id=holder_id,
            holder_name=holder_name,
            related_document=doc,
            days_remaining=days,
            due_date=expiration_date,
        )

    invalidate_stats_cache(str(provider.id))
    return doc


def _build_document_alert_title(document_type, holder_name, days):
    label = document_type.replace('_', ' ').title()
    if days is None or days >= 0:
        return f'{label} Expiring in {days} Days — {holder_name}'
    return f'{label} Expired — {holder_name}'


def _build_document_alert_description(document_type, holder_name, days, expiration_date):
    label = document_type.replace('_', ' ').title()
    if days is not None and days < 0:
        return (
            f'The {label} for {holder_name} expired on {expiration_date}. '
            f'Immediate renewal required.'
        )
    return (
        f'The {label} for {holder_name} expires on {expiration_date} '
        f'({days} days remaining). Please renew before expiry.'
    )
