from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .models import DriverLocation, ActiveTripTracking
from .serializers import DriverLocationSerializer, ActiveTripTrackingSerializer


# Returns all currently online drivers for the authenticated provider with their live GPS positions
class LiveDriversView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Filter to only online drivers belonging to this provider
        locations = DriverLocation.objects.filter(
            provider=request.user,
            is_online=True,
        ).select_related('driver', 'driver__vehicle')

        serializer = DriverLocationSerializer(
            locations, many=True, context={'request': request}
        )

        return CustomResponse.success(
            message='Live driver locations fetched successfully.',
            data={
                'online_drivers': serializer.data,
                'total_online': locations.count(),
            },
            status_code=200
        )


# Returns the current live tracking state for a specific trip — driver position, ETA, and tracking status
class LiveTripView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        from apps.trips.models import Trip

        # Scope the trip to this provider to prevent cross-provider access
        trip = get_object_or_404(Trip, id=id, provider=request.user)

        # Live tracking only makes sense while the trip is actively moving
        if trip.status not in ('on_way', 'in_progress', 'awaiting_signature'):
            return CustomResponse.error(
                message=f'Trip is not currently active (status: {trip.status}). '
                        f'Live tracking is only available for on_way, in_progress, or awaiting_signature trips.',
                status_code=400
            )

        # Fetch the active tracking record — created by driver_app when the trip starts
        try:
            tracking = ActiveTripTracking.objects.select_related(
                'trip', 'driver', 'trip__passenger'
            ).prefetch_related('trip__passenger_contacts').get(trip=trip)
        except ActiveTripTracking.DoesNotExist:
            return CustomResponse.error(
                message='No active tracking record found for this trip.',
                status_code=404
            )

        serializer = ActiveTripTrackingSerializer(tracking, context={'request': request})
        return CustomResponse.success(
            message='Live trip tracking fetched successfully.',
            data=serializer.data,
            status_code=200
        )
