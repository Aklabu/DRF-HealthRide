from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .models import (
    Facility, FacilityPrimaryContact, FacilityBillingContact,
    FacilityContract, FacilityPricing, FacilityTax, FacilityDocument,
)
from .serializers import (
    FacilityListSerializer,
    FacilityCreateSerializer,
    FacilityHeaderSerializer,
    FacilityPrimaryContactSerializer,
    FacilityBillingContactSerializer,
    FacilityContractSerializer,
    FacilityPricingSerializer,
    FacilityTaxSerializer,
    FacilityDocumentSerializer,
    FacilityDocumentUploadSerializer,
)


# facilites list and creation endpoint
class FacilityListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        queryset = Facility.objects.filter(provider=request.user).select_related(
            'primary_contact', 'contract'
        )

        # Search by facility name or primary contact name
        search = request.query_params.get('search')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(facility_name__icontains=search) |
                Q(primary_contact__full_name__icontains=search)
            )

        # Header stats
        stats = queryset.aggregate(
            total_revenue=Sum('total_revenue'),
            outstanding=Sum('outstanding_amount'),
        )

        header = {
            'total_facilities': queryset.count(),
            'active_facilities': queryset.filter(status='active').count(),
            'total_revenue': str(stats['total_revenue'] or '0.00'),
            'outstanding': str(stats['outstanding'] or '0.00'),
        }

        serializer = FacilityListSerializer(queryset, many=True, context={'request': request})
        return CustomResponse.success(
            message='Facilities fetched successfully.',
            data={'header': header, 'facilities': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = FacilityCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        with transaction.atomic():
            # Create facility — facility_id auto-generated in model save()
            facility = Facility.objects.create(
                provider=request.user,
                facility_name=data['facility_name'],
                facility_type=data['facility_type'],
                street_address=data.get('street_address', ''),
                city=data.get('city', ''),
                state=data.get('state', ''),
                zip_code=data.get('zip_code', ''),
                pickup_instructions=data.get('pickup_instructions'),
                status='active',
            )

            # Create primary contact
            FacilityPrimaryContact.objects.create(
                facility=facility,
                full_name=data.get('pc_full_name', ''),
                title=data.get('pc_title', ''),
                department=data.get('pc_department', ''),
                phone=data.get('pc_phone', ''),
                email=data.get('pc_email', ''),
            )

            # Create billing contact
            FacilityBillingContact.objects.create(
                facility=facility,
                full_name=data.get('bc_full_name', ''),
                title=data.get('bc_title', ''),
                department=data.get('bc_department', ''),
                phone=data.get('bc_phone', ''),
                email=data.get('bc_email', ''),
                insurance_no=data.get('bc_insurance_no', ''),
            )

            # Create contract
            FacilityContract.objects.create(
                facility=facility,
                contract_number=data['contract_number'],
                start_date=data.get('start_date'),
                end_date=data.get('end_date'),
                billing_cycle=data.get('billing_cycle', 'monthly'),
                payment_terms=data.get('payment_terms', ''),
                volume_commitment=data.get('volume_commitment', 0),
                auto_renewal=data.get('auto_renewal', False),
                status='active',
            )

            # Create pricing
            FacilityPricing.objects.create(
                facility=facility,
                standard_sedan_rate=data.get('standard_sedan_rate', 0),
                wheelchair_accessible_rate=data.get('wheelchair_accessible_rate', 0),
                stretcher_transport_rate=data.get('stretcher_transport_rate', 0),
                wait_time_rate=data.get('wait_time_rate', 0),
                discount_percentage=data.get('discount_percentage', 0),
                minimum_trips=data.get('minimum_trips', 0),
            )

            # Create tax record
            tax = FacilityTax.objects.create(
                facility=facility,
                tax_id=data.get('tax_id', ''),
                tax_exempt=False,
                w9_on_file=False,
            )

            # Handle document uploads
            doc_map = {
                'w9_tax_form': 'W9 Tax Form',
                'hipaa_agreement': 'HIPAA Agreement',
                'insurance_certificate': 'Insurance Certificate',
            }
            for field, doc_name in doc_map.items():
                f = data.get(field)
                if f:
                    FacilityDocument.objects.create(
                        facility=facility,
                        document_name=doc_name,
                        document_type=field,
                        file=f,
                    )
                    # Set w9_on_file flag if w9 doc uploaded
                    if field == 'w9_tax_form':
                        tax.w9_on_file = True
                        tax.save(update_fields=['w9_on_file'])

        response_serializer = FacilityHeaderSerializer(facility)
        return CustomResponse.success(
            message='Facility created successfully.',
            data=response_serializer.data,
            status_code=201
        )


# Facility detail endpoint
class FacilityDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        facility = get_object_or_404(Facility, id=id, provider=request.user)
        serializer = FacilityHeaderSerializer(facility)
        return CustomResponse.success(
            message='Facility fetched successfully.',
            data=serializer.data,
            status_code=200
        )


# Contact + location overview endpoint
class FacilityOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get_facility(self, facility_id, provider):
        return get_object_or_404(Facility, id=facility_id, provider=provider)

    def _build_overview(self, facility):
        # Primary contact
        try:
            pc = facility.primary_contact
            primary_contact = FacilityPrimaryContactSerializer(pc).data
        except FacilityPrimaryContact.DoesNotExist:
            primary_contact = None

        # Billing contact
        try:
            bc = facility.billing_contact
            billing_contact = FacilityBillingContactSerializer(bc).data
        except FacilityBillingContact.DoesNotExist:
            billing_contact = None

        # Location
        location = {
            'street_address': facility.street_address,
            'city': facility.city,
            'state': facility.state,
            'zip_code': facility.zip_code,
            'pickup_instructions': facility.pickup_instructions,
        }

        # Performance overview — computed on demand
        completion_rate = 0.0
        completed_trips = 0
        total_trips = facility.total_trips
        average_trips_per_week = 0.0
        on_time_payments_pct = 0.0

        # Compute completion rate from trips app if available
        try:
            from apps.trips.models import Trip
            completed_trips = Trip.objects.filter(
                facility=facility, status='completed'
            ).count()
            if total_trips > 0:
                completion_rate = round((completed_trips / total_trips) * 100, 2)
        except Exception:
            pass

        # Average trips per week since contract start
        try:
            contract = facility.contract
            if contract.start_date:
                days_active = (timezone.now().date() - contract.start_date).days
                weeks_active = max(days_active / 7, 1)
                average_trips_per_week = round(total_trips / weeks_active, 2)
        except Exception:
            pass

        performance_overview = {
            'completion_rate': completion_rate,
            'completed_trips': completed_trips,
            'total_trips': total_trips,
            'average_trips_per_week': average_trips_per_week,
            'on_time_payments_pct': on_time_payments_pct,
        }

        return {
            'primary_contact': primary_contact,
            'billing_contact': billing_contact,
            'location': location,
            'performance_overview': performance_overview,
        }

    def get(self, request, id):
        facility = self.get_facility(id, request.user)
        return CustomResponse.success(
            message='Facility overview fetched successfully.',
            data=self._build_overview(facility),
            status_code=200
        )

    def patch(self, request, id):
        facility = self.get_facility(id, request.user)

        with transaction.atomic():
            # Update primary contact if pc_ fields provided
            pc_fields = ['pc_full_name', 'pc_title', 'pc_department', 'pc_phone', 'pc_email']
            pc_data = {}
            for field in pc_fields:
                if field in request.data:
                    pc_data[field.replace('pc_', '')] = request.data[field]

            if pc_data:
                pc, _ = FacilityPrimaryContact.objects.get_or_create(facility=facility)
                for attr, val in pc_data.items():
                    setattr(pc, attr, val)
                pc.save()

            # Update billing contact if bc_ fields provided
            bc_fields = ['bc_full_name', 'bc_title', 'bc_department', 'bc_phone', 'bc_email', 'bc_insurance_no']
            bc_data = {}
            for field in bc_fields:
                if field in request.data:
                    key = field.replace('bc_', '')
                    # insurance_no keeps its name
                    bc_data[key] = request.data[field]

            if bc_data:
                bc, _ = FacilityBillingContact.objects.get_or_create(facility=facility)
                for attr, val in bc_data.items():
                    setattr(bc, attr, val)
                bc.save()

            # Update location fields on Facility model directly
            location_fields = ['street_address', 'city', 'state', 'zip_code', 'pickup_instructions']
            location_updates = {f: request.data[f] for f in location_fields if f in request.data}
            if location_updates:
                for attr, val in location_updates.items():
                    setattr(facility, attr, val)
                facility.save(update_fields=list(location_updates.keys()))

        return CustomResponse.success(
            message='Facility overview updated successfully.',
            data=self._build_overview(facility),
            status_code=200
        )


# Contract + billing + tax details endpoint
class FacilityDetailsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_facility(self, facility_id, provider):
        return get_object_or_404(Facility, id=facility_id, provider=provider)

    def _build_details(self, facility):
        # Contract — evaluate expiry at read time
        try:
            contract = facility.contract
            # If end_date passed and no auto_renewal — return as expired
            if contract.end_date and contract.end_date < timezone.now().date() and not contract.auto_renewal:
                contract_status = 'expired'
            else:
                contract_status = contract.status

            contract_data = {
                'contract_number': contract.contract_number,
                'status': contract_status,
                'start_date': contract.start_date,
                'end_date': contract.end_date,
                'billing_cycle': contract.billing_cycle,
                'payment_terms': contract.payment_terms,
                'volume_commitment': contract.volume_commitment,
                'auto_renewal': contract.auto_renewal,
            }
        except FacilityContract.DoesNotExist:
            contract_data = None

        # Pricing
        try:
            pricing = facility.pricing
            pricing_data = FacilityPricingSerializer(pricing).data
        except FacilityPricing.DoesNotExist:
            pricing_data = None

        # Tax
        try:
            tax = facility.tax
            tax_data = {
                'tax_id': tax.tax_id,
                'tax_exempt': tax.tax_exempt,
                'w9_form': {'on_file': tax.w9_on_file},
            }
        except FacilityTax.DoesNotExist:
            tax_data = None

        return {
            'contract': contract_data,
            'pricing': pricing_data,
            'tax': tax_data,
        }

    def get(self, request, id):
        facility = self.get_facility(id, request.user)
        return CustomResponse.success(
            message='Facility details fetched successfully.',
            data=self._build_details(facility),
            status_code=200
        )

    def patch(self, request, id):
        facility = self.get_facility(id, request.user)

        # Separate contract, pricing, tax, and document fields
        contract_fields = [
            'contract_number', 'start_date', 'end_date',
            'billing_cycle', 'payment_terms', 'volume_commitment', 'auto_renewal'
        ]
        pricing_fields = [
            'standard_sedan_rate', 'wheelchair_accessible_rate',
            'stretcher_transport_rate', 'wait_time_rate',
            'discount_percentage', 'minimum_trips'
        ]
        tax_fields = ['tax_id', 'tax_exempt']

        contract_data = {k: request.data[k] for k in contract_fields if k in request.data}
        pricing_data = {k: request.data[k] for k in pricing_fields if k in request.data}
        tax_data = {k: request.data[k] for k in tax_fields if k in request.data}
        w9_file = request.FILES.get('w9_tax_form')

        with transaction.atomic():
            # Update contract
            if contract_data:
                contract, _ = FacilityContract.objects.get_or_create(facility=facility)
                serializer = FacilityContractSerializer(contract, data=contract_data, partial=True)
                if not serializer.is_valid():
                    return CustomResponse.error(
                        message='Validation failed.',
                        status_code=400,
                        errors=serializer.errors
                    )
                contract = serializer.save()

                # If end_date updated to future and was expired — reactivate
                today = timezone.now().date()
                if contract.end_date and contract.end_date >= today and contract.status == 'expired':
                    contract.status = 'active'
                    contract.save(update_fields=['status'])

            # Update pricing
            if pricing_data:
                pricing, _ = FacilityPricing.objects.get_or_create(facility=facility)
                serializer = FacilityPricingSerializer(pricing, data=pricing_data, partial=True)
                if not serializer.is_valid():
                    return CustomResponse.error(
                        message='Validation failed.',
                        status_code=400,
                        errors=serializer.errors
                    )
                serializer.save()

            # Update tax
            if tax_data:
                tax, _ = FacilityTax.objects.get_or_create(facility=facility)
                serializer = FacilityTaxSerializer(tax, data=tax_data, partial=True)
                if not serializer.is_valid():
                    return CustomResponse.error(
                        message='Validation failed.',
                        status_code=400,
                        errors=serializer.errors
                    )
                serializer.save()

            # Handle w9 document upload
            if w9_file:
                allowed = ['application/pdf', 'image/jpeg', 'image/png']
                if hasattr(w9_file, 'content_type') and w9_file.content_type not in allowed:
                    return CustomResponse.error(
                        message='Only PDF, JPG, and PNG files are allowed.',
                        status_code=400
                    )
                FacilityDocument.objects.create(
                    facility=facility,
                    document_name='W9 Tax Form',
                    document_type='w9_tax_form',
                    file=w9_file,
                )
                # Keep w9_on_file flag in sync
                tax, _ = FacilityTax.objects.get_or_create(facility=facility)
                tax.w9_on_file = True
                tax.save(update_fields=['w9_on_file'])

        return CustomResponse.success(
            message='Facility details updated successfully.',
            data=self._build_details(facility),
            status_code=200
        )


# Invoice list from billing app
class FacilityBillingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        facility = get_object_or_404(Facility, id=id, provider=request.user)

        # Pull invoices from billing app — graceful fallback
        invoices = []
        try:
            from apps.billing.models import Invoice
            invoice_qs = Invoice.objects.filter(
                facility=facility,
                provider=request.user
            ).order_by('-issue_date')

            # Search by invoice number
            search = request.query_params.get('search')
            if search:
                invoice_qs = invoice_qs.filter(invoice_number__icontains=search)

            # Filter by date range
            date_from = request.query_params.get('date_from')
            date_to = request.query_params.get('date_to')
            if date_from:
                invoice_qs = invoice_qs.filter(issue_date__gte=date_from)
            if date_to:
                invoice_qs = invoice_qs.filter(issue_date__lte=date_to)

            for inv in invoice_qs:
                invoices.append({
                    'invoice_number': inv.invoice_number,
                    'period': f'{inv.period_start} – {inv.period_end}',
                    'paid_date': inv.paid_date,
                    'issue_date': inv.issue_date,
                    'due_date': inv.due_date,
                    'trips_count': inv.trips_count,
                    'amount': str(inv.amount),
                    'status': inv.status,
                })
        except Exception:
            # Billing app not yet available
            pass

        return CustomResponse.success(
            message='Facility billing fetched successfully.',
            data={'invoices': invoices},
            status_code=200
        )


# Trip history from trips app
class FacilityTripsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        facility = get_object_or_404(Facility, id=id, provider=request.user)

        # Pull trips from trips app — graceful fallback
        trips = []
        try:
            from apps.trips.models import Trip
            trip_qs = Trip.objects.filter(
                facility=facility,
                provider=request.user,
                status='completed'
            ).select_related('driver', 'passenger').order_by('-pickup_date', '-pickup_time')

            for trip in trip_qs:
                passenger_name = ''
                if trip.passenger:
                    passenger_name = trip.passenger.full_name

                trips.append({
                    'invoice_number': str(trip.id),
                    'status': trip.status,
                    'date_time': str(trip.pickup_date),
                    'passenger_name': passenger_name,
                    'pickup_location': trip.pickup_address,
                    'trip_type': trip.trip_type,
                    'amount': str(trip.total_amount),
                })
        except Exception:
            # Trips app not yet available
            pass

        return CustomResponse.success(
            message='Facility trips fetched successfully.',
            data={'trips': trips},
            status_code=200
        )


# Document management endpoint
class FacilityDocumentView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, id):
        facility = get_object_or_404(Facility, id=id, provider=request.user)
        documents = FacilityDocument.objects.filter(facility=facility).order_by('-uploaded_date')
        serializer = FacilityDocumentSerializer(documents, many=True, context={'request': request})
        return CustomResponse.success(
            message='Documents fetched successfully.',
            data={'documents': serializer.data},
            status_code=200
        )

    def post(self, request, id):
        facility = get_object_or_404(Facility, id=id, provider=request.user)

        serializer = FacilityDocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        document = FacilityDocument.objects.create(
            facility=facility,
            document_name=data['document_name'],
            document_type=data['document_type'],
            file=data['file'],
        )

        # Keep w9_on_file flag in sync
        if data['document_type'] == 'w9_tax_form':
            FacilityTax.objects.filter(facility=facility).update(w9_on_file=True)

        response_serializer = FacilityDocumentSerializer(document, context={'request': request})
        return CustomResponse.success(
            message='Document uploaded successfully.',
            data=response_serializer.data,
            status_code=201
        )