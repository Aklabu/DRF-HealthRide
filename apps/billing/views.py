from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import JSONParser
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from decimal import Decimal

from utils.response import CustomResponse
from .models import (
    StripeAccount, BankAccount, Invoice, InvoiceItem,
    InvoiceTemplate, LateFeeConfig,
)
from .serializers import (
    StripeStatusSerializer,
    BankAccountSerializer,
    BankAccountWriteSerializer,
    InvoiceListSerializer,
    InvoiceDetailSerializer,
    InvoiceCreateSerializer,
    InvoiceStatusUpdateSerializer,
    InvoiceTemplateSerializer,
    LateFeeConfigSerializer,
)
from .encryption import encrypt_field, mask_number
from .utils import generate_invoice_number, update_facility_on_payment


# Stripe Account Connect
class StripeConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check if already connected
        try:
            existing = request.user.stripe_account
            if existing.onboarding_completed:
                return CustomResponse.error(
                    message='Stripe account is already connected and onboarding is complete.',
                    status_code=400
                )
        except StripeAccount.DoesNotExist:
            existing = None

        try:
            import stripe
            from django.conf import settings
            stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')

            if not existing:
                # Create a new Stripe Connect Express account
                account = stripe.Account.create(
                    type='express',
                    email=request.user.business_email,
                    business_type='company',
                )
                stripe_account = StripeAccount.objects.create(
                    provider=request.user,
                    stripe_account_id=account.id,
                    is_connected=False,
                    onboarding_completed=False,
                )
            else:
                stripe_account = existing

            # Generate onboarding link
            dashboard_url = getattr(settings, 'PROVIDER_DASHBOARD_URL', 'https://healthride.com/billing')
            link = stripe.AccountLink.create(
                account=stripe_account.stripe_account_id,
                refresh_url=dashboard_url,
                return_url=dashboard_url,
                type='account_onboarding',
            )

            return CustomResponse.success(
                message='Stripe onboarding link generated.',
                data={
                    'onboarding_url': link.url,
                    'stripe_account_id': stripe_account.stripe_account_id,
                },
                status_code=200
            )

        except Exception as e:
            return CustomResponse.error(
                message=f'Stripe error: {str(e)}',
                status_code=400
            )


class StripeStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            stripe_account = request.user.stripe_account
        except StripeAccount.DoesNotExist:
            return CustomResponse.success(
                message='No Stripe account connected.',
                data={'connected': False},
                status_code=200
            )

        # Sync status from Stripe
        try:
            import stripe
            from django.conf import settings
            stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')

            account = stripe.Account.retrieve(stripe_account.stripe_account_id)
            stripe_account.charges_enabled = account.charges_enabled
            stripe_account.payouts_enabled = account.payouts_enabled
            stripe_account.onboarding_completed = account.details_submitted
            stripe_account.is_connected = account.charges_enabled
            stripe_account.save(update_fields=[
                'charges_enabled', 'payouts_enabled',
                'onboarding_completed', 'is_connected',
            ])
        except Exception:
            pass  # Return cached status if Stripe API fails

        serializer = StripeStatusSerializer(stripe_account)
        return CustomResponse.success(
            message='Stripe status fetched.',
            data=serializer.data,
            status_code=200
        )


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    """
    Stripe webhook receiver — authenticated via Stripe signature, not JWT.
    Must be excluded from CSRF protection.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        import stripe
        from django.conf import settings

        stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')

        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError):
            return CustomResponse.error(message='Invalid webhook signature.', status_code=400)

        event_type = event['type']
        data = event['data']['object']

        if event_type == 'account.updated':
            try:
                acct = StripeAccount.objects.get(stripe_account_id=data['id'])
                acct.charges_enabled = data.get('charges_enabled', False)
                acct.payouts_enabled = data.get('payouts_enabled', False)
                acct.onboarding_completed = data.get('details_submitted', False)
                acct.is_connected = data.get('charges_enabled', False)
                acct.save(update_fields=[
                    'charges_enabled', 'payouts_enabled',
                    'onboarding_completed', 'is_connected',
                ])
            except StripeAccount.DoesNotExist:
                pass

        elif event_type == 'account.application.deauthorized':
            try:
                acct = StripeAccount.objects.get(stripe_account_id=data.get('id', ''))
                acct.is_connected = False
                acct.onboarding_completed = False
                acct.save(update_fields=['is_connected', 'onboarding_completed'])
            except StripeAccount.DoesNotExist:
                pass

        elif event_type == 'payment_intent.succeeded':
            # Match to invoice by metadata if set, otherwise skip
            metadata = data.get('metadata', {})
            invoice_id = metadata.get('invoice_id')
            if invoice_id:
                try:
                    invoice = Invoice.objects.get(id=invoice_id)
                    invoice.status = 'paid'
                    invoice.paid_date = timezone.now().date()
                    invoice.save(update_fields=['status', 'paid_date'])
                    update_facility_on_payment(invoice)
                except Invoice.DoesNotExist:
                    pass

        elif event_type == 'payment_intent.payment_failed':
            # Log failure — notify provider via notifications app
            metadata = data.get('metadata', {})
            invoice_id = metadata.get('invoice_id')
            if invoice_id:
                try:
                    from apps.notifications.utils import notify_payment_failed
                    invoice = Invoice.objects.get(id=invoice_id)
                    notify_payment_failed(invoice)
                except Exception:
                    pass

        # Always return 200 to Stripe — prevents retries on unknown event types
        return CustomResponse.success(
            message='Webhook received.',
            data={'received': True},
            status_code=200
        )


#  Bank Account Management
class BankAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            bank = request.user.bank_account
        except BankAccount.DoesNotExist:
            return CustomResponse.error(
                message='No bank account on file.',
                status_code=404
            )
        serializer = BankAccountSerializer(bank)
        return CustomResponse.success(
            message='Bank account fetched.',
            data=serializer.data,
            status_code=200
        )

    def post(self, request):
        serializer = BankAccountWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        raw_account = data['account_number']
        raw_routing = data['routing_number']

        # Encrypt full account number
        encrypted = encrypt_field(raw_account)

        # Mask for display
        masked_account = mask_number(raw_account, keep_last=4)
        masked_routing = mask_number(raw_routing, keep_last=4)

        bank, _ = BankAccount.objects.update_or_create(
            provider=request.user,
            defaults={
                'bank_name': data['bank_name'],
                'routing_number': masked_routing,
                'account_number': masked_account,
                'account_number_encrypted': encrypted,
                'verified': False,  # re-verification required on any update
            }
        )

        return CustomResponse.success(
            message='Bank account saved.',
            data={
                'bank_name': bank.bank_name,
                'routing_number': bank.routing_number,
                'account_number': bank.account_number,
                'verified': bank.verified,
            },
            status_code=200
        )


# Invoices Management
class InvoiceListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Invoice.objects.filter(
            provider=request.user
        ).select_related('facility')

        # Filters
        facility_id = request.query_params.get('facility_id')
        if facility_id:
            queryset = queryset.filter(facility__id=facility_id)

        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        date_from = request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(issue_date__gte=date_from)

        date_to = request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(issue_date__lte=date_to)

        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(invoice_number__icontains=search)

        serializer = InvoiceListSerializer(queryset, many=True)
        return CustomResponse.success(
            message='Invoices fetched.',
            data={'invoices': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = InvoiceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate facility belongs to provider
        facility = None
        if data.get('facility_id'):
            from apps.facilities.models import Facility
            try:
                facility = Facility.objects.get(id=data['facility_id'], provider=request.user)
            except Facility.DoesNotExist:
                return CustomResponse.error(
                    message='Facility not found or does not belong to your account.',
                    status_code=404
                )

        # Query qualifying trips
        from apps.trips.models import Trip
        trip_qs = Trip.objects.filter(
            provider=request.user,
            status='completed',
            pickup_date__gte=data['period_start'],
            pickup_date__lte=data['period_end'],
            payment_status__in=['unpaid', 'payment_later'],
        )

        if facility:
            trip_qs = trip_qs.filter(facility=facility)
        else:
            trip_qs = trip_qs.filter(facility__isnull=True)

        # Exclude trips already in an invoice
        already_billed = InvoiceItem.objects.values_list('trip_id', flat=True)
        trip_qs = trip_qs.exclude(id__in=already_billed)

        trips = list(trip_qs.select_related('passenger').prefetch_related('passenger_contacts'))

        if not trips:
            return CustomResponse.error(
                message='No unbilled trips found for this period.',
                status_code=400
            )

        # Compute totals
        subtotal = sum(t.estimated_total for t in trips)
        trips_count = len(trips)

        # Fetch invoice template
        today = timezone.now().date()
        payment_terms_days = 30
        try:
            template = request.user.invoice_template
            payment_terms_days = template.payment_terms
        except Exception:
            pass

        due_date = today + timezone.timedelta(days=payment_terms_days)

        with transaction.atomic():
            invoice_number = generate_invoice_number(request.user)

            invoice = Invoice.objects.create(
                provider=request.user,
                facility=facility,
                invoice_number=invoice_number,
                period_start=data['period_start'],
                period_end=data['period_end'],
                issue_date=today,
                due_date=due_date,
                trips_count=trips_count,
                subtotal=subtotal,
                amount=subtotal,
                status='draft',
                notes=data.get('notes'),
            )

            # Create snapshotted line items
            for trip in trips:
                passenger_name = ''
                if trip.passenger:
                    passenger_name = trip.passenger.full_name
                else:
                    contact = trip.passenger_contacts.first()
                    if contact:
                        passenger_name = contact.full_name

                InvoiceItem.objects.create(
                    invoice=invoice,
                    trip=trip,
                    trip_date=trip.pickup_date,
                    passenger_name=passenger_name,
                    pickup_address=trip.pickup_address,
                    dropoff_address=trip.dropoff_address,
                    trip_type=trip.trip_type,
                    amount=trip.estimated_total,
                )

            # Update facility outstanding stats
            if facility:
                facility.outstanding_amount = (
                    (facility.outstanding_amount or Decimal('0.00')) + subtotal
                )
                facility.outstanding_last_date = due_date
                facility.save(update_fields=['outstanding_amount', 'outstanding_last_date'])

        # Send invoice email async — updates status to sent on success
        try:
            from .tasks import send_invoice_email
            send_invoice_email.delay(str(invoice.id))
        except Exception:
            # Celery unavailable — send synchronously as fallback
            try:
                from .tasks import send_invoice_email as send_sync
                send_sync(str(invoice.id))
            except Exception:
                pass

        invoice.refresh_from_db()
        response_serializer = InvoiceDetailSerializer(invoice)
        return CustomResponse.success(
            message='Invoice generated successfully.',
            data=response_serializer.data,
            status_code=201
        )


class InvoiceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        invoice = get_object_or_404(Invoice, id=id, provider=request.user)
        serializer = InvoiceDetailSerializer(invoice)
        return CustomResponse.success(
            message='Invoice fetched.',
            data=serializer.data,
            status_code=200
        )


class InvoiceStatusUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        invoice = get_object_or_404(Invoice, id=id, provider=request.user)

        serializer = InvoiceStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        new_status = serializer.validated_data['status']
        current = invoice.status

        # Validate transitions
        allowed = {
            'draft': ['sent'],
            'sent': ['paid'],
            'overdue': ['paid'],
        }
        if new_status not in allowed.get(current, []):
            return CustomResponse.error(
                message=f'Cannot transition invoice from "{current}" to "{new_status}".',
                status_code=400
            )

        with transaction.atomic():
            if new_status == 'paid':
                invoice.paid_date = timezone.now().date()
                invoice.status = 'paid'
                invoice.save(update_fields=['status', 'paid_date'])
                update_facility_on_payment(invoice)

            elif new_status == 'sent':
                invoice.status = 'sent'
                invoice.save(update_fields=['status'])
                # Re-send email
                try:
                    from .tasks import send_invoice_email
                    send_invoice_email.delay(str(invoice.id))
                except Exception:
                    pass

        response_serializer = InvoiceListSerializer(invoice)
        return CustomResponse.success(
            message=f'Invoice status updated to {new_status}.',
            data=response_serializer.data,
            status_code=200
        )


# Invoice Template View
class InvoiceTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            template = request.user.invoice_template
            serializer = InvoiceTemplateSerializer(template)
            data = serializer.data
        except InvoiceTemplate.DoesNotExist:
            # Return defaults
            data = {
                'invoice_number_prefix': 'INV',
                'payment_terms': 30,
                'footer_text': None,
            }
        return CustomResponse.success(
            message='Invoice template fetched.',
            data=data,
            status_code=200
        )

    def patch(self, request):
        template, _ = InvoiceTemplate.objects.get_or_create(provider=request.user)
        serializer = InvoiceTemplateSerializer(template, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()
        return CustomResponse.success(
            message='Invoice template updated.',
            data=serializer.data,
            status_code=200
        )


# Late Fee Config View
class LateFeeConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            config = request.user.late_fee_config
            serializer = LateFeeConfigSerializer(config)
            data = serializer.data
        except LateFeeConfig.DoesNotExist:
            data = {
                'late_fee_percentage': '0.00',
                'grace_period_days': 0,
            }
        return CustomResponse.success(
            message='Late fee config fetched.',
            data=data,
            status_code=200
        )

    def patch(self, request):
        config, _ = LateFeeConfig.objects.get_or_create(provider=request.user)
        serializer = LateFeeConfigSerializer(config, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()
        return CustomResponse.success(
            message='Late fee config updated.',
            data=serializer.data,
            status_code=200
        )
