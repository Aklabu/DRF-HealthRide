import uuid
from django.db import models
from apps.accounts.models import Provider
from apps.facilities.models import Facility
from apps.trips.models import Trip


# Invoice status choices
INVOICE_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('sent', 'Sent'),
    ('paid', 'Paid'),
    ('overdue', 'Overdue'),
]


# Stripe Connect account — OneToOne per provider
class StripeAccount(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='stripe_account')

    # Stripe Connect account ID — e.g. acct_XXXXXXXXXX
    stripe_account_id = models.CharField(max_length=100, unique=True)
    is_connected = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)

    # Synced from Stripe on status check and webhook
    charges_enabled = models.BooleanField(default=False)
    payouts_enabled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stripe_accounts'

    def __str__(self):
        return f'Stripe account for {self.provider.business_email}'


# Bank account — OneToOne per provider, account number encrypted at rest
class BankAccount(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='bank_account')

    bank_name = models.CharField(max_length=255)

    # Masked display values — e.g. ****4321
    routing_number = models.CharField(max_length=20)       # stored masked
    account_number = models.CharField(max_length=20)       # stored masked (last 4 digits)

    # Full account number encrypted — never returned in API responses
    account_number_encrypted = models.TextField()

    verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bank_accounts'

    def __str__(self):
        return f'Bank account for {self.provider.business_email}'


# Invoice — one per billing period per facility (or provider-level)
class Invoice(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='invoices')
    facility = models.ForeignKey(
        Facility, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )

    # Auto-generated from InvoiceTemplate prefix — e.g. HRI-000123
    invoice_number = models.CharField(max_length=50, unique=True)

    period_start = models.DateField()
    period_end = models.DateField()
    issue_date = models.DateField()
    due_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)

    trips_count = models.PositiveIntegerField(default=0)

    # Financials
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    late_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    status = models.CharField(max_length=10, choices=INVOICE_STATUS_CHOICES, default='draft')
    late_fee_applied = models.BooleanField(default=False)

    notes = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'invoices'
        ordering = ['-issue_date']

    def __str__(self):
        return f'{self.invoice_number} — {self.status}'

    def _generate_invoice_number(self):
        # generate invoice number based on provider's template prefix and next sequence
        try:
            template = self.provider.invoice_template
            prefix = template.invoice_number_prefix or 'INV'
        except Exception:
            prefix = 'INV'

        # Derive next sequence from MAX existing invoice number for this provider
        existing = Invoice.objects.filter(
            provider=self.provider,
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

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._generate_invoice_number()
        super().save(*args, **kwargs)


# Invoice line items — snapshotted at generation time, never updated
class InvoiceItem(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')

    # PROTECT — a billed trip cannot be deleted
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name='invoice_items')

    # Snapshot fields — reflect trip data at invoice generation time
    trip_date = models.DateField()
    passenger_name = models.CharField(max_length=255)
    pickup_address = models.TextField()
    dropoff_address = models.TextField()
    trip_type = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'invoice_items'

    def __str__(self):
        return f'Item {self.trip.trip_number} on {self.invoice.invoice_number}'


# Invoice template — OneToOne per provider
class InvoiceTemplate(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='invoice_template')

    # Prefix for invoice numbers — e.g. HRI, NEMT, INV
    invoice_number_prefix = models.CharField(max_length=10, default='INV')

    # Days until due — e.g. 30 for Net 30
    payment_terms = models.PositiveIntegerField(default=30)

    footer_text = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'invoice_templates'

    def __str__(self):
        return f'Invoice template for {self.provider.business_email}'


# Late fee configuration — OneToOne per provider
class LateFeeConfig(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='late_fee_config')

    # e.g. 1.5 for 1.5%
    late_fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    # Days after due_date before late fee is applied
    grace_period_days = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'late_fee_configs'

    def __str__(self):
        return f'Late fee config for {self.provider.business_email}'
