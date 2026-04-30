from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .models import Vehicle, VehicleInsurance, VehicleMaintenance, VehicleDocument
from .serializers import (
    VehicleListSerializer,
    VehicleCreateSerializer,
    VehicleHeaderSerializer,
    VehicleHeaderUpdateSerializer,
    VehicleSpecificationsSerializer,
    VehicleInsuranceSerializer,
    VehicleMaintenanceSerializer,
    VehicleDocumentSerializer,
    VehicleDocumentUploadSerializer,
    AssignDriverSerializer,
)


# create and list vehicles
class VehicleListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        # All vehicles scoped to this provider
        queryset = Vehicle.objects.filter(provider=request.user).select_related(
            'assigned_driver', 'insurance'
        ).prefetch_related('documents')

        # Search by license_plate or vehicle id
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(license_plate__icontains=search)

        # Header stats
        header = {
            'total_vehicles': queryset.count(),
            'active_vehicles': queryset.filter(status='active').count(),
            'in_maintenance': queryset.filter(status='in_maintenance').count(),
            'on_trip': queryset.filter(status='on_trip').count(),
        }

        serializer = VehicleListSerializer(queryset, many=True, context={'request': request})

        return CustomResponse.success(
            message='Vehicles fetched successfully.',
            data={'header': header, 'vehicles': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = VehicleCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate license_plate unique within this provider
        if Vehicle.objects.filter(
            provider=request.user,
            license_plate=data['license_plate']
        ).exists():
            return CustomResponse.error(
                message='A vehicle with this license plate already exists under your account.',
                status_code=400
            )

        # Validate assigned driver if provided
        assigned_driver = None
        if data.get('assigned_driver'):
            try:
                from apps.drivers.models import Driver
                assigned_driver = Driver.objects.get(
                    id=data['assigned_driver'],
                    provider=request.user
                )
                # Check driver not already assigned to another vehicle
                if Vehicle.objects.filter(assigned_driver=assigned_driver).exists():
                    return CustomResponse.error(
                        message='This driver is already assigned to another vehicle.',
                        status_code=400
                    )
            except Exception:
                return CustomResponse.error(
                    message='Driver not found or does not belong to your account.',
                    status_code=404
                )

        with transaction.atomic():
            # Create vehicle
            vehicle = Vehicle.objects.create(
                provider=request.user,
                brand=data['brand'],
                model_number=data['model_number'],
                year=data['year'],
                color=data['color'],
                license_plate=data['license_plate'],
                vin_number=data['vin_number'],
                purchase_price=data.get('purchase_price'),
                purchase_date=data.get('purchase_date'),
                vehicle_type=data['vehicle_type'],
                seating_capacity=data['seating_capacity'],
                accessibility_features=data['accessibility_features'],
                ramp_type=data.get('ramp_type', 'none'),
                securement_system=data.get('securement_system', ''),
                status=data.get('status', 'active'),
                registration_state=data.get('registration_state', ''),
                registration_expiry=data.get('registration_expiry'),
                assigned_driver=assigned_driver,
                assigned_since=timezone.now().date() if assigned_driver else None,
            )

            # Create insurance record atomically
            VehicleInsurance.objects.create(
                vehicle=vehicle,
                insurance_provider=data.get('insurance_provider', ''),
                policy_number=data.get('policy_number', ''),
                expiry_date=data.get('expiry_date'),
                monthly_premium=data.get('monthly_premium', 0),
                liability_coverage=data.get('liability_coverage', 0),
                collision_coverage=data.get('collision_coverage', 0),
                comprehensive_coverage=data.get('comprehensive_coverage', 0),
            )

            # Create baseline maintenance record
            VehicleMaintenance.objects.create(
                vehicle=vehicle,
                maintenance_type='Initial Setup',
                current_mileage=data.get('current_mileage', 0),
                service_interval=data.get('service_interval', 0),
                last_service=data.get('last_service_date'),
                last_service_mileage=data.get('last_service_mileage', 0),
                next_service_mileage=(
                    data.get('last_service_mileage', 0) + data.get('service_interval', 0)
                ),
                mileage_at_service=data.get('current_mileage', 0),
                upcoming_service='First scheduled service',
            )

            # Upload registration document if provided
            if data.get('registration_document'):
                VehicleDocument.objects.create(
                    vehicle=vehicle,
                    document_name='Vehicle Registration',
                    document_type='registration',
                    file=data['registration_document'],
                )

            # Upload insurance document if provided
            if data.get('insurance_document'):
                VehicleDocument.objects.create(
                    vehicle=vehicle,
                    document_name='Vehicle Insurance',
                    document_type='insurance',
                    file=data['insurance_document'],
                )

            # Update driver's vehicle back-reference if assigned
            if assigned_driver:
                assigned_driver.vehicle = vehicle
                assigned_driver.save(update_fields=['vehicle'])

        response_serializer = VehicleHeaderSerializer(vehicle, context={'request': request})
        return CustomResponse.success(
            message='Vehicle created successfully.',
            data=response_serializer.data,
            status_code=201
        )


# retrieve or update vehicle header info
class VehicleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_vehicle(self, vehicle_id, provider):
        return get_object_or_404(Vehicle, id=vehicle_id, provider=provider)

    def get(self, request, id):
        vehicle = self.get_vehicle(id, request.user)
        serializer = VehicleHeaderSerializer(vehicle, context={'request': request})

        # Read-only computed fields — placeholders, trips app will populate these
        data = serializer.data
        data['total_trips'] = 0
        data['total_hours'] = 0
        data['avg_fuel_economy'] = 0
        data['total_revenue'] = '0.00'

        return CustomResponse.success(
            message='Vehicle fetched successfully.',
            data=data,
            status_code=200
        )

    def patch(self, request, id):
        vehicle = self.get_vehicle(id, request.user)

        # Reject read-only fields
        read_only = ['id', 'total_trips', 'total_hours', 'avg_fuel_economy', 'total_revenue']
        for field in read_only:
            if field in request.data:
                return CustomResponse.error(
                    message=f'Field "{field}" is read-only and cannot be updated.',
                    status_code=400
                )

        serializer = VehicleHeaderUpdateSerializer(vehicle, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()

        return CustomResponse.success(
            message='Vehicle updated successfully.',
            data=VehicleHeaderSerializer(vehicle, context={'request': request}).data,
            status_code=200
        )


# retrieve or update vehicle specifications + insurance
class VehicleSpecificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get_vehicle(self, vehicle_id, provider):
        return get_object_or_404(Vehicle, id=vehicle_id, provider=provider)

    def get(self, request, id):
        vehicle = self.get_vehicle(id, request.user)

        try:
            insurance = vehicle.insurance
        except VehicleInsurance.DoesNotExist:
            insurance = None

        data = {
            'specifications': {
                'model': vehicle.model_number,
                'year': vehicle.year,
                'color': vehicle.color,
                'vin': vehicle.vin_number,
                'license_plate': vehicle.license_plate,
                'purchase_date': vehicle.purchase_date,
                'accessibility_features': vehicle.accessibility_features,
                'capacity': vehicle.seating_capacity,
                'ramp_type': vehicle.ramp_type,
                'securement_system': vehicle.securement_system,
                'registration_state': vehicle.registration_state,
                'registration_expiry': vehicle.registration_expiry,
            },
            'inspection': {
                'last_inspection': vehicle.last_inspection,
                'next_due': vehicle.next_due,
                'inspector': vehicle.inspector,
            },
            'insurance': VehicleInsuranceSerializer(insurance).data if insurance else None,
        }

        return CustomResponse.success(
            message='Vehicle specifications fetched successfully.',
            data=data,
            status_code=200
        )

    def patch(self, request, id):
        vehicle = self.get_vehicle(id, request.user)

        # Reject system-set inspection fields
        read_only = ['last_inspection', 'next_due', 'inspector']
        for field in read_only:
            if field in request.data:
                return CustomResponse.error(
                    message=f'Field "{field}" is read-only and set by the compliance system.',
                    status_code=400
                )

        # Separate vehicle and insurance fields
        insurance_fields = [
            'insurance_provider', 'policy_number', 'expiry_date',
            'monthly_premium', 'liability_coverage', 'collision_coverage', 'comprehensive_coverage'
        ]
        vehicle_data = {k: v for k, v in request.data.items() if k not in insurance_fields}
        insurance_data = {k: v for k, v in request.data.items() if k in insurance_fields}

        with transaction.atomic():
            # Update vehicle spec fields
            if vehicle_data:
                spec_serializer = VehicleSpecificationsSerializer(
                    vehicle, data=vehicle_data, partial=True
                )
                if not spec_serializer.is_valid():
                    return CustomResponse.error(
                        message='Validation failed.',
                        status_code=400,
                        errors=spec_serializer.errors
                    )
                spec_serializer.save()

            # Update or create insurance record
            if insurance_data:
                insurance, _ = VehicleInsurance.objects.get_or_create(vehicle=vehicle)
                ins_serializer = VehicleInsuranceSerializer(
                    insurance, data=insurance_data, partial=True
                )
                if not ins_serializer.is_valid():
                    return CustomResponse.error(
                        message='Validation failed.',
                        status_code=400,
                        errors=ins_serializer.errors
                    )
                ins_serializer.save()

        # Return full updated specs
        return self.get(request, id)


# retrieve maintenance records + summary
class VehicleMaintenanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        vehicle = get_object_or_404(Vehicle, id=id, provider=request.user)

        records = VehicleMaintenance.objects.filter(vehicle=vehicle).order_by('-scheduled_date')

        # Build summary from latest records
        latest = records.first()
        last_completed = records.filter(completed_date__isnull=False).first()
        upcoming = records.filter(
            next_service_date__isnull=False,
            next_service_date__gte=timezone.now().date()
        ).order_by('next_service_date').first()

        summary = {
            'current_mileage': latest.current_mileage if latest else 0,
            'last_service': last_completed.completed_date if last_completed else None,
            'next_service': upcoming.next_service_date if upcoming else None,
            'upcoming_service': upcoming.upcoming_service if upcoming else None,
        }

        serializer = VehicleMaintenanceSerializer(records, many=True)

        return CustomResponse.success(
            message='Maintenance records fetched successfully.',
            data={'summary': summary, 'records': serializer.data},
            status_code=200
        )


# retrieve or upload vehicle documents
class VehicleDocumentView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, id):
        vehicle = get_object_or_404(Vehicle, id=id, provider=request.user)
        documents = VehicleDocument.objects.filter(vehicle=vehicle).order_by('-uploaded_date')
        serializer = VehicleDocumentSerializer(documents, many=True, context={'request': request})

        return CustomResponse.success(
            message='Documents fetched successfully.',
            data=serializer.data,
            status_code=200
        )

    def post(self, request, id):
        vehicle = get_object_or_404(Vehicle, id=id, provider=request.user)

        serializer = VehicleDocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        document = VehicleDocument.objects.create(
            vehicle=vehicle,
            document_name=data['document_name'],
            document_type=data['document_type'],
            file=data['file'],
            expires_date=data.get('expires_date'),
        )

        # Flag for compliance if expiry is within 60 days
        if document.expires_date:
            threshold = timezone.now().date() + timezone.timedelta(days=60)
            if document.expires_date <= threshold:
                # Compliance app will pick this up — placeholder for integration
                pass

        response_serializer = VehicleDocumentSerializer(document, context={'request': request})
        return CustomResponse.success(
            message='Document uploaded successfully.',
            data=response_serializer.data,
            status_code=201
        )


# assign or unassign driver to vehicle
class VehicleAssignDriverView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        vehicle = get_object_or_404(Vehicle, id=id, provider=request.user)

        serializer = AssignDriverSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        driver_id = serializer.validated_data['driver_id']

        with transaction.atomic():
            # Unassign flow
            if driver_id is None:
                old_driver = vehicle.assigned_driver
                vehicle.assigned_driver = None
                vehicle.assigned_since = None
                vehicle.status = 'active'
                vehicle.save(update_fields=['assigned_driver', 'assigned_since', 'status'])

                # Clear driver's vehicle back-reference
                if old_driver:
                    old_driver.vehicle = None
                    old_driver.save(update_fields=['vehicle'])

                return CustomResponse.success(
                    message='Driver unassigned successfully.',
                    data={
                        'vehicle_id': str(vehicle.id),
                        'assigned_driver': None,
                        'assigned_since': None,
                    },
                    status_code=200
                )

            # Assign flow
            try:
                from apps.drivers.models import Driver
                driver = Driver.objects.get(id=driver_id, provider=request.user)
            except Exception:
                return CustomResponse.error(
                    message='Driver not found or does not belong to your account.',
                    status_code=404
                )

            # Check driver not already assigned to a different vehicle
            already_assigned = Vehicle.objects.filter(
                assigned_driver=driver
            ).exclude(id=vehicle.id).first()

            if already_assigned:
                return CustomResponse.error(
                    message=f'Driver is already assigned to vehicle {already_assigned.license_plate}.',
                    status_code=400
                )

            # Clear old driver from this vehicle if any
            if vehicle.assigned_driver and vehicle.assigned_driver != driver:
                old_driver = vehicle.assigned_driver
                old_driver.vehicle = None
                old_driver.save(update_fields=['vehicle'])

            # Assign new driver
            vehicle.assigned_driver = driver
            vehicle.assigned_since = timezone.now().date()
            vehicle.save(update_fields=['assigned_driver', 'assigned_since'])

            # Update driver's vehicle back-reference
            driver.vehicle = vehicle
            driver.save(update_fields=['vehicle'])

        return CustomResponse.success(
            message='Driver assigned successfully.',
            data={
                'vehicle_id': str(vehicle.id),
                'assigned_driver': {
                    'name': driver.full_name,
                    'driver_id': str(driver.id),
                },
                'assigned_since': vehicle.assigned_since,
            },
            status_code=200
        )