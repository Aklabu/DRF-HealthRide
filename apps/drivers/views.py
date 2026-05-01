from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .models import (
    Driver, DriverLicense, DriverEmergencyContact,
    DriverCertification, DriverDocument, DriverAvailability,
    DriverWorkLog, DriverPayout,
)
from .serializers import (
    DriverListSerializer,
    DriverCreateSerializer,
    DriverHeaderSerializer,
    DriverHeaderUpdateSerializer,
    DriverEmergencyContactSerializer,
    DriverCertificationSerializer,
    DriverDocumentSerializer,
    DriverDocumentUploadSerializer,
    DriverAvailabilitySerializer,
    AvailabilityUpdateItemSerializer,
    DriverWorkLogSerializer,
    DriverPayoutSerializer,
    DriverPayoutCreateSerializer,
)
from .utils import generate_driver_password, hash_password, send_driver_welcome_email


# Helper — get Mon and Sun of a given week offset (0 = current, -1 = last)
def get_week_window(offset=0):
    today = timezone.now().date()
    monday = today - timezone.timedelta(days=today.weekday()) + timezone.timedelta(weeks=offset)
    sunday = monday + timezone.timedelta(days=6)
    return monday, sunday


# driver list and create view
class DriverListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        queryset = Driver.objects.filter(provider=request.user).select_related('vehicle')

        # Search across name, phone, email
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                full_name__icontains=search
            ) | queryset.filter(
                phone_number__icontains=search
            ) | queryset.filter(
                email__icontains=search
            )
            queryset = queryset.filter(provider=request.user)

        header = {
            'total_drivers': queryset.count(),
            'active_drivers': queryset.filter(status_employment='active').count(),
            'available_drivers': queryset.filter(status_availability='available').count(),
            'on_trip': queryset.filter(status_availability='on_trip').count(),
        }

        serializer = DriverListSerializer(queryset, many=True)
        return CustomResponse.success(
            message='Drivers fetched successfully.',
            data={'header': header, 'drivers': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = DriverCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate vehicle if provided
        vehicle = None
        if data.get('vehicle_id'):
            try:
                from apps.vehicles.models import Vehicle
                vehicle = Vehicle.objects.get(id=data['vehicle_id'], provider=request.user)
                # Check not already assigned to another driver
                if vehicle.assigned_driver is not None:
                    return CustomResponse.error(
                        message='This vehicle is already assigned to another driver.',
                        status_code=400
                    )
            except Exception:
                return CustomResponse.error(
                    message='Vehicle not found or does not belong to your account.',
                    status_code=404
                )

        # Generate and hash password
        plain_password = generate_driver_password()
        hashed_password = hash_password(plain_password)

        with transaction.atomic():
            # Create driver
            driver = Driver.objects.create(
                provider=request.user,
                full_name=data['full_name'],
                phone_number=data['phone_number'],
                email=data['email'],
                date_of_birth=data.get('date_of_birth'),
                home_address=data.get('home_address', ''),
                password=hashed_password,
                status_employment=data.get('status_employment', 'active'),
                status_availability='off_duty',
                hourly_rate=data.get('hourly_rate', 0),
                vehicle=vehicle,
            )

            # Override joined_date if provided
            if data.get('employment_start_date'):
                Driver.objects.filter(id=driver.id).update(joined_date=data['employment_start_date'])

            # Create license record
            DriverLicense.objects.create(
                driver=driver,
                license_number=data['license_number'],
                license_state=data['license_state'],
                license_expiry_date=data.get('license_expiry_date'),
            )

            # Create emergency contact
            DriverEmergencyContact.objects.create(
                driver=driver,
                name=data.get('emergency_name', ''),
                phone=data.get('emergency_phone', ''),
                relationship=data.get('emergency_relationship', ''),
            )

            # Create certification records
            certs = [
                {'cert_type': 'cpr', 'expiry_date': data.get('cpr_expiry_date'), 'is_active': data.get('cpr_is_active', False)},
                {'cert_type': 'first_aid', 'expiry_date': data.get('first_aid_expiry_date'), 'is_active': data.get('first_aid_is_active', False)},
                {'cert_type': 'wheelchair_assistance', 'expiry_date': None, 'is_active': data.get('wheelchair_assistance', False)},
                {'cert_type': 'defensive_driving', 'expiry_date': None, 'is_active': data.get('defensive_driving', False)},
            ]
            for cert in certs:
                DriverCertification.objects.create(driver=driver, **cert)

            # Create document records for any uploaded files
            doc_map = {
                'driver_license_file': 'driver_license',
                'insurance_file': 'insurance',
                'cpr_certificate_file': 'cpr_certificate',
                'background_check_file': 'background_check',
            }
            for field, doc_type in doc_map.items():
                if data.get(field):
                    DriverDocument.objects.create(
                        driver=driver,
                        document_type=doc_type,
                        file=data[field],
                    )

            # Create exactly 7 availability records
            submitted_days = {day['day_of_week']: day for day in data.get('availability', [])}
            for day_num in range(7):
                day_data = submitted_days.get(day_num, {})
                is_available = day_data.get('is_available', False)
                DriverAvailability.objects.create(
                    driver=driver,
                    day_of_week=day_num,
                    is_available=is_available,
                    start_time=day_data.get('start_time') if is_available else None,
                    end_time=day_data.get('end_time') if is_available else None,
                )

            # Bidirectional vehicle assignment
            if vehicle:
                vehicle.assigned_driver = driver
                vehicle.assigned_since = timezone.now().date()
                vehicle.save(update_fields=['assigned_driver', 'assigned_since'])

        # Send welcome email — synchronous but non-blocking for the response
        try:
            send_driver_welcome_email(driver.email, driver.full_name, plain_password)
        except Exception:
            # Do not fail driver creation if email fails
            pass

        response_serializer = DriverHeaderSerializer(driver, context={'request': request})
        return CustomResponse.success(
            message='Driver created successfully.',
            data=response_serializer.data,
            status_code=201
        )


# Driver detail view — GET header info, PATCH update editable fields
class DriverDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_driver(self, driver_id, provider):
        return get_object_or_404(Driver, id=driver_id, provider=provider)

    def get(self, request, id):
        driver = self.get_driver(id, request.user)
        serializer = DriverHeaderSerializer(driver, context={'request': request})
        return CustomResponse.success(
            message='Driver fetched successfully.',
            data=serializer.data,
            status_code=200
        )

    def patch(self, request, id):
        driver = self.get_driver(id, request.user)

        # Reject read-only fields
        read_only = ['total_trips', 'on_time_rate', 'joined_date', 'id']
        for field in read_only:
            if field in request.data:
                return CustomResponse.error(
                    message=f'Field "{field}" is read-only and cannot be updated.',
                    status_code=400
                )

        serializer = DriverHeaderUpdateSerializer(driver, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()

        return CustomResponse.success(
            message='Driver updated successfully.',
            data=DriverHeaderSerializer(driver, context={'request': request}).data,
            status_code=200
        )


# Driver overview view — GET emergency contact + vehicle info + certifications, PATCH update these fields
class DriverOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get_driver(self, driver_id, provider):
        return get_object_or_404(Driver, id=driver_id, provider=provider)

    def get(self, request, id):
        driver = self.get_driver(id, request.user)

        # Emergency contact
        try:
            ec = driver.emergency_contact
            emergency_contact = {'name': ec.name, 'phone': ec.phone, 'relationship': ec.relationship}
        except DriverEmergencyContact.DoesNotExist:
            emergency_contact = None

        # Vehicle info
        vehicle_info = None
        if driver.vehicle:
            vehicle_info = {
                'vehicle_id': str(driver.vehicle.id),
                'vehicle_type': driver.vehicle.vehicle_type,
            }

        # Certifications — one per type
        certs = {c.cert_type: {'expiry_date': c.expiry_date, 'is_active': c.is_active}
                 for c in driver.certifications.all()}

        return CustomResponse.success(
            message='Driver overview fetched successfully.',
            data={
                'emergency_contact': emergency_contact,
                'vehicle_information': vehicle_info,
                'certifications': {
                    'cpr': certs.get('cpr', {'expiry_date': None, 'is_active': False}),
                    'first_aid': certs.get('first_aid', {'expiry_date': None, 'is_active': False}),
                    'wheelchair_assistance': certs.get('wheelchair_assistance', {'expiry_date': None, 'is_active': False}),
                    'defensive_driving': certs.get('defensive_driving', {'expiry_date': None, 'is_active': False}),
                },
            },
            status_code=200
        )

    def patch(self, request, id):
        driver = self.get_driver(id, request.user)

        with transaction.atomic():
            # Update emergency contact if any ec fields provided
            ec_fields = ['emergency_name', 'emergency_phone', 'emergency_relationship']
            ec_data = {k.replace('emergency_', ''): request.data[k] for k in ec_fields if k in request.data}
            if ec_data:
                DriverEmergencyContact.objects.update_or_create(
                    driver=driver,
                    defaults={
                        'name': ec_data.get('name', ''),
                        'phone': ec_data.get('phone', ''),
                        'relationship': ec_data.get('relationship', ''),
                    }
                )

            # Bidirectional vehicle assignment if vehicle_id provided
            if 'vehicle_id' in request.data:
                vehicle_id = request.data.get('vehicle_id')
                if vehicle_id:
                    try:
                        from apps.vehicles.models import Vehicle
                        new_vehicle = Vehicle.objects.get(id=vehicle_id, provider=request.user)
                    except Exception:
                        return CustomResponse.error(
                            message='Vehicle not found or does not belong to your account.',
                            status_code=404
                        )

                    # Clear old vehicle assignment
                    if driver.vehicle and driver.vehicle != new_vehicle:
                        old_vehicle = driver.vehicle
                        old_vehicle.assigned_driver = None
                        old_vehicle.assigned_since = None
                        old_vehicle.save(update_fields=['assigned_driver', 'assigned_since'])

                    # Assign new vehicle
                    driver.vehicle = new_vehicle
                    driver.save(update_fields=['vehicle'])
                    new_vehicle.assigned_driver = driver
                    new_vehicle.assigned_since = timezone.now().date()
                    new_vehicle.save(update_fields=['assigned_driver', 'assigned_since'])
                else:
                    # Unassign vehicle
                    if driver.vehicle:
                        old_vehicle = driver.vehicle
                        old_vehicle.assigned_driver = None
                        old_vehicle.assigned_since = None
                        old_vehicle.save(update_fields=['assigned_driver', 'assigned_since'])
                    driver.vehicle = None
                    driver.save(update_fields=['vehicle'])

            # Upsert certifications if provided
            cert_field_map = {
                'cpr_expiry_date': ('cpr', 'expiry_date'),
                'cpr_is_active': ('cpr', 'is_active'),
                'first_aid_expiry_date': ('first_aid', 'expiry_date'),
                'first_aid_is_active': ('first_aid', 'is_active'),
                'wheelchair_assistance_expiry_date': ('wheelchair_assistance', 'expiry_date'),
                'wheelchair_assistance_is_active': ('wheelchair_assistance', 'is_active'),
                'defensive_driving_expiry_date': ('defensive_driving', 'expiry_date'),
                'defensive_driving_is_active': ('defensive_driving', 'is_active'),
            }
            cert_updates = {}
            for req_field, (cert_type, attr) in cert_field_map.items():
                if req_field in request.data:
                    if cert_type not in cert_updates:
                        cert_updates[cert_type] = {}
                    cert_updates[cert_type][attr] = request.data[req_field]

            for cert_type, updates in cert_updates.items():
                DriverCertification.objects.update_or_create(
                    driver=driver,
                    cert_type=cert_type,
                    defaults=updates
                )

        return self.get(request, id)


# Document view — GET list of documents with latest file + expiry, PATCH upload new document
class DriverDocumentView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_driver(self, driver_id, provider):
        return get_object_or_404(Driver, id=driver_id, provider=provider)

    def get(self, request, id):
        driver = self.get_driver(id, request.user)

        doc_types = ['driver_license', 'insurance', 'cpr_certificate', 'background_check']
        grouped = {}

        for doc_type in doc_types:
            # Latest document per type
            latest = driver.documents.filter(document_type=doc_type).order_by('-upload_date').first()
            if latest:
                grouped[doc_type] = {
                    'file': request.build_absolute_uri(latest.file.url) if latest.file else None,
                    'upload_date': latest.upload_date,
                    'expire_date': latest.expire_date,
                }
            else:
                grouped[doc_type] = None

        return CustomResponse.success(
            message='Documents fetched successfully.',
            data=grouped,
            status_code=200
        )

    def patch(self, request, id):
        driver = self.get_driver(id, request.user)

        serializer = DriverDocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Create new record — preserves history
        document = DriverDocument.objects.create(
            driver=driver,
            document_type=data['document_type'],
            file=data['file'],
            expire_date=data.get('expire_date'),
        )

        # Flag for compliance if expiry within 60 days
        if document.expire_date:
            threshold = timezone.now().date() + timezone.timedelta(days=60)
            if document.expire_date <= threshold:
                # Compliance app integration placeholder
                pass

        return self.get(request, id)


# Driver availability view — GET weekly availability, PATCH update availability
class DriverAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get_driver(self, driver_id, provider):
        return get_object_or_404(Driver, id=driver_id, provider=provider)

    def get(self, request, id):
        driver = self.get_driver(id, request.user)
        availability = driver.availability.order_by('day_of_week')
        serializer = DriverAvailabilitySerializer(availability, many=True)
        return CustomResponse.success(
            message='Availability fetched successfully.',
            data={'availability': serializer.data},
            status_code=200
        )

    def patch(self, request, id):
        driver = self.get_driver(id, request.user)

        # Expect a list of day objects
        days = request.data if isinstance(request.data, list) else request.data.get('availability', [])

        errors = []
        for day in days:
            item_serializer = AvailabilityUpdateItemSerializer(data=day)
            if not item_serializer.is_valid():
                errors.append(item_serializer.errors)
                continue

            day_data = item_serializer.validated_data
            is_available = day_data['is_available']

            DriverAvailability.objects.update_or_create(
                driver=driver,
                day_of_week=day_data['day_of_week'],
                defaults={
                    'is_available': is_available,
                    'start_time': day_data.get('start_time') if is_available else None,
                    'end_time': day_data.get('end_time') if is_available else None,
                }
            )

        if errors:
            return CustomResponse.error(
                message='Some days failed validation.',
                status_code=400,
                errors=errors
            )

        return self.get(request, id)


# payment information view — GET earnings summary for current/last week + average, PATCH not allowed
class DriverWorkingHoursView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        driver = get_object_or_404(Driver, id=id, provider=request.user)

        current_monday, current_sunday = get_week_window(0)
        last_monday, last_sunday = get_week_window(-1)

        # Aggregate current week
        current_logs = DriverWorkLog.objects.filter(driver=driver, date__gte=current_monday, date__lte=current_sunday)
        current_totals = current_logs.aggregate(hours=Sum('hours_worked'), earnings=Sum('earnings'))

        # Aggregate last week
        last_logs = DriverWorkLog.objects.filter(driver=driver, date__gte=last_monday, date__lte=last_sunday)
        last_totals = last_logs.aggregate(hours=Sum('hours_worked'), earnings=Sum('earnings'))

        # Average hours across the two weeks
        current_hours = current_totals['hours'] or 0
        last_hours = last_totals['hours'] or 0
        avg_hours = (current_hours + last_hours) / 2

        # Build per-day breakdown for current week — fill missing days with zeros
        logs_by_date = {log.date: log for log in current_logs}
        current_week_days = []
        for i in range(7):
            day_date = current_monday + timezone.timedelta(days=i)
            day_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][i]
            log = logs_by_date.get(day_date)
            current_week_days.append({
                'day': day_name,
                'date': day_date,
                'hours_worked': log.hours_worked if log else '0.00',
                'trips_completed': log.trips_completed if log else 0,
                'total_earnings': log.earnings if log else '0.00',
                'status': log.status if log else 'off_day',
            })

        # Week totals
        week_total_trips = current_logs.aggregate(trips=Sum('trips_completed'))['trips'] or 0

        return CustomResponse.success(
            message='Working hours fetched successfully.',
            data={
                'payment_information': {
                    'hourly_rate': str(driver.hourly_rate),
                    'this_week': {
                        'total_hours': str(current_totals['hours'] or '0.00'),
                        'total_earnings': str(current_totals['earnings'] or '0.00'),
                    },
                    'last_week': {
                        'total_hours': str(last_totals['hours'] or '0.00'),
                        'total_earnings': str(last_totals['earnings'] or '0.00'),
                    },
                    'average_per_week': {
                        'hours': str(round(avg_hours, 2)),
                    },
                },
                'current_week': current_week_days,
                'week_total': {
                    'total_hours': str(current_totals['hours'] or '0.00'),
                    'total_trips': week_total_trips,
                    'total_earnings': str(current_totals['earnings'] or '0.00'),
                },
            },
            status_code=200
        )


# earnings view — GET earnings summary for current/last week + month + total, PATCH not allowed
class DriverEarningsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        driver = get_object_or_404(Driver, id=id, provider=request.user)

        today = timezone.now().date()

        # Current week Mon–Sun
        this_monday, this_sunday = get_week_window(0)

        # Last week Mon–Sun
        last_monday, last_sunday = get_week_window(-1)

        # Current calendar month
        month_start = today.replace(day=1)

        # Aggregate earnings
        this_week = driver.work_logs.filter(date__gte=this_monday, date__lte=this_sunday).aggregate(total=Sum('earnings'))['total'] or 0
        last_week = driver.work_logs.filter(date__gte=last_monday, date__lte=last_sunday).aggregate(total=Sum('earnings'))['total'] or 0
        this_month = driver.work_logs.filter(date__gte=month_start).aggregate(total=Sum('earnings'))['total'] or 0

        # Total paid out + unpaid accrued
        total_paid_out = driver.payouts.aggregate(total=Sum('total_amount'))['total'] or 0
        total_accrued = driver.work_logs.aggregate(total=Sum('earnings'))['total'] or 0
        total_earned = total_paid_out + (total_accrued - total_paid_out)

        # Last 10 payouts
        recent_payouts = driver.payouts.order_by('-created_at')[:10]
        payout_serializer = DriverPayoutSerializer(recent_payouts, many=True)

        return CustomResponse.success(
            message='Earnings fetched successfully.',
            data={
                'header': {
                    'this_week': str(this_week),
                    'last_week': str(last_week),
                    'this_month': str(this_month),
                    'total_earned': str(total_accrued),
                },
                'recent_payouts': payout_serializer.data,
            },
            status_code=200
        )


# payout view — POST with from_date + to_date to create payout record for that range
class DriverPayoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        driver = get_object_or_404(Driver, id=id, provider=request.user)

        serializer = DriverPayoutCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data
        from_date = data['from_date']
        to_date = data['to_date']
        confirm = data['confirm']

        # Check for overlapping payout records
        overlap = DriverPayout.objects.filter(
            driver=driver,
            from_date__lte=to_date,
            to_date__gte=from_date,
        ).exists()

        if overlap:
            return CustomResponse.error(
                message='A payout already exists that overlaps with this date range.',
                status_code=400
            )

        # Aggregate hours from work logs within range
        logs = DriverWorkLog.objects.filter(
            driver=driver,
            date__gte=from_date,
            date__lte=to_date,
            status='worked'
        )
        totals = logs.aggregate(hours=Sum('hours_worked'))
        total_hours = totals['hours'] or 0
        total_amount = total_hours * driver.hourly_rate

        # Preview — return computed values without saving
        if not confirm:
            return CustomResponse.success(
                message='Payout preview computed.',
                data={
                    'from_date': from_date,
                    'to_date': to_date,
                    'total_hours': str(total_hours),
                    'hourly_rate': str(driver.hourly_rate),
                    'total_amount': str(total_amount),
                    'confirmed': False,
                },
                status_code=200
            )

        # Confirm — create payout record
        payout = DriverPayout.objects.create(
            driver=driver,
            from_date=from_date,
            to_date=to_date,
            total_hours=total_hours,
            total_amount=total_amount,
        )

        return CustomResponse.success(
            message='Payout created successfully.',
            data={
                'payout_id': str(payout.id),
                'from_date': payout.from_date,
                'to_date': payout.to_date,
                'total_hours': str(payout.total_hours),
                'total_amount': str(payout.total_amount),
                'created_at': payout.created_at,
                'confirmed': True,
            },
            status_code=201
        )