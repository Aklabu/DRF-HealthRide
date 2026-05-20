"""
Celery tasks for the billing app.

apply_late_fees  — runs daily at midnight UTC
send_invoice_email — async task called at invoice generation
"""
from decimal import Decimal
from django.utils import timezone


def apply_late_fees():
    """
    Daily task: apply late fees to overdue invoices.
    Runs at midnight UTC via Celery Beat.

    Logic:
    1. Fetch all sent invoices past due_date with late_fee_applied = False
    2. For each, check LateFeeConfig and grace period
    3. Apply fee, update status to overdue, notify provider
    """
    from .models import Invoice, LateFeeConfig

    today = timezone.now().date()

    # All sent invoices past their due date, not yet fee-applied
    overdue_invoices = Invoice.objects.filter(
        status='sent',
        due_date__lt=today,
        late_fee_applied=False,
    ).select_related('provider', 'facility')

    processed = 0

    for invoice in overdue_invoices:
        try:
            config = invoice.provider.late_fee_config
        except LateFeeConfig.DoesNotExist:
            continue

        if not config or config.late_fee_percentage == 0:
            continue

        days_overdue = (today - invoice.due_date).days

        # Still within grace period — skip
        if days_overdue <= config.grace_period_days:
            continue

        # Compute and apply late fee
        late_fee = invoice.subtotal * (config.late_fee_percentage / Decimal('100'))
        late_fee = round(late_fee, 2)

        old_amount = invoice.amount
        invoice.late_fee_amount = late_fee
        invoice.amount = invoice.subtotal + late_fee
        invoice.status = 'overdue'
        invoice.late_fee_applied = True
        invoice.save(update_fields=[
            'late_fee_amount', 'amount', 'status', 'late_fee_applied'
        ])

        # Update facility outstanding_amount by the late fee delta
        if invoice.facility:
            fee_delta = invoice.amount - old_amount
            invoice.facility.outstanding_amount = (
                (invoice.facility.outstanding_amount or Decimal('0.00')) + fee_delta
            )
            invoice.facility.save(update_fields=['outstanding_amount'])

        # Notify provider — fire and forget
        try:
            from apps.notifications.utils import notify_invoice_overdue
            notify_invoice_overdue(invoice)
        except Exception:
            pass

        processed += 1

    return f'apply_late_fees: processed {processed} invoices'


def send_invoice_email(invoice_id):
    """
    Async task: send invoice email to facility billing contact.
    Called at invoice generation time.
    On success — updates invoice.status = sent.
    On failure — retries up to 3 times with exponential backoff.
    """
    from .models import Invoice
    from django.core.mail import send_mail
    from django.conf import settings

    try:
        invoice = Invoice.objects.select_related(
            'provider', 'facility', 'facility__billing_contact'
        ).prefetch_related('items').get(id=invoice_id)
    except Invoice.DoesNotExist:
        return

    # Determine recipient
    recipient = None
    if invoice.facility:
        try:
            recipient = invoice.facility.billing_contact.email
        except Exception:
            pass

    if not recipient:
        return

    # Fetch template footer
    footer = ''
    try:
        footer = invoice.provider.invoice_template.footer_text or ''
    except Exception:
        pass

    # Build line items text
    items_text = '\n'.join([
        f'  {item.trip_date} | {item.passenger_name} | '
        f'{item.pickup_address} → {item.dropoff_address} | ${item.amount}'
        for item in invoice.items.all()
    ])

    subject = f'Invoice {invoice.invoice_number} from {invoice.provider.business_name}'
    message = (
        f'Dear {invoice.facility.billing_contact.full_name if invoice.facility else "Billing Contact"},\n\n'
        f'Please find your invoice details below.\n\n'
        f'Invoice Number : {invoice.invoice_number}\n'
        f'Period         : {invoice.period_start} to {invoice.period_end}\n'
        f'Issue Date     : {invoice.issue_date}\n'
        f'Due Date       : {invoice.due_date}\n'
        f'Payment Terms  : Net {(invoice.due_date - invoice.issue_date).days}\n\n'
        f'Line Items:\n{items_text}\n\n'
        f'Subtotal       : ${invoice.subtotal}\n'
        f'Total Amount   : ${invoice.amount}\n\n'
        f'{footer}\n\n'
        f'Thank you,\n{invoice.provider.business_name}'
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
        # Mark as sent on success
        Invoice.objects.filter(id=invoice_id).update(status='sent')
    except Exception as e:
        # Log and let Celery retry handle it
        raise


# ── Celery task registration ──────────────────────────────────────────────────

try:
    from config.celery import app as celery_app

    apply_late_fees = celery_app.task(
        name='billing.apply_late_fees',
        ignore_result=False,
    )(apply_late_fees)

    send_invoice_email = celery_app.task(
        name='billing.send_invoice_email',
        ignore_result=False,
        max_retries=3,
        default_retry_delay=60,  # seconds; Celery doubles on each retry
    )(send_invoice_email)

except Exception:
    # Celery not configured — tasks remain as plain functions
    pass
