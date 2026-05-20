"""
Billing utility functions called by the trips app and internal billing logic.
"""
from decimal import Decimal
from django.utils import timezone


def handle_completed_trip(trip):
    """
    Called by trips app on trip completion.
    Placeholder — billing app processes trips in batch via POST /billing/invoices/.
    Individual trip completion does not auto-generate an invoice; it just marks
    the trip as available for the next invoice generation cycle.
    """
    pass


def flag_cancellation_fee(trip, cancellation_fee):
    """
    Called by trips app when a trip is cancelled within the cancellation window.
    Flags the trip for a cancellation fee to be included in the next invoice.
    For now this is a no-op placeholder — the billing app will pick up
    cancelled trips with a fee flag in a future billing cycle.
    """
    pass


def generate_invoice_number(provider):
    """
    Generate the next invoice number for a provider using their InvoiceTemplate prefix.
    Uses MAX(invoice_number) to derive the sequence — safe for concurrent creation
    when wrapped in a transaction with select_for_update on the Invoice table.
    """
    from .models import Invoice

    try:
        template = provider.invoice_template
        prefix = template.invoice_number_prefix or 'INV'
    except Exception:
        prefix = 'INV'

    existing = Invoice.objects.filter(
        provider=provider,
        invoice_number__startswith=f'{prefix}-'
    ).order_by('-invoice_number').values_list('invoice_number', flat=True).first()

    if existing:
        try:
            last_num = int(existing.replace(f'{prefix}-', ''))
        except ValueError:
            last_num = 0
    else:
        last_num = 0

    return f'{prefix}-{str(last_num + 1).zfill(6)}'


def update_facility_on_payment(invoice):
    """
    Update facility denormalized stats when an invoice is marked paid.
    - Deduct invoice.amount from facility.outstanding_amount
    - Recompute facility.outstanding_last_date
    - Update facility.avg_payment_days rolling average
    """
    from .models import Invoice

    facility = invoice.facility
    if not facility:
        return

    today = timezone.now().date()
    days_to_pay = (today - invoice.issue_date).days

    # Deduct from outstanding
    facility.outstanding_amount = max(
        Decimal('0.00'),
        (facility.outstanding_amount or Decimal('0.00')) - invoice.amount
    )

    # Recompute outstanding_last_date — due_date of next oldest unpaid invoice
    next_unpaid = Invoice.objects.filter(
        facility=facility,
        status__in=['sent', 'overdue'],
    ).exclude(id=invoice.id).order_by('due_date').first()

    facility.outstanding_last_date = next_unpaid.due_date if next_unpaid else None

    # Rolling average: new_avg = (old_avg × n + days_to_pay) / (n + 1)
    paid_count = Invoice.objects.filter(
        facility=facility,
        status='paid',
    ).exclude(id=invoice.id).count()

    old_avg = facility.avg_payment_days or Decimal('0.00')
    new_avg = (old_avg * paid_count + days_to_pay) / (paid_count + 1)
    facility.avg_payment_days = round(new_avg, 2)

    facility.save(update_fields=[
        'outstanding_amount', 'outstanding_last_date', 'avg_payment_days'
    ])
