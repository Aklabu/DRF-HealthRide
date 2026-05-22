from rest_framework import serializers
from datetime import date


class DateRangeSerializer(serializers.Serializer):
    # Shared date range validation for all report endpoints
    date_range_start = serializers.DateField()
    date_range_end = serializers.DateField()
    group_by = serializers.ChoiceField(
        choices=['day', 'week', 'month'], required=False, allow_null=True
    )

    def validate(self, attrs):
        start = attrs['date_range_start']
        end = attrs['date_range_end']

        if start > end:
            raise serializers.ValidationError(
                {'date_range_end': 'date_range_end must be on or after date_range_start.'}
            )

        delta = (end - start).days
        if delta > 365:
            raise serializers.ValidationError(
                'Date range cannot exceed 365 days.'
            )

        return attrs


class TripVolumeQuerySerializer(DateRangeSerializer):
    pass


class DriverHoursQuerySerializer(DateRangeSerializer):
    driver_id = serializers.UUIDField(required=False, allow_null=True)


class PassengerServiceQuerySerializer(serializers.Serializer):
    date_range_start = serializers.DateField()
    date_range_end = serializers.DateField()
    group_by = serializers.ChoiceField(
        choices=['week', 'month'], required=False, allow_null=True
    )

    def validate(self, attrs):
        start = attrs['date_range_start']
        end = attrs['date_range_end']
        if start > end:
            raise serializers.ValidationError(
                {'date_range_end': 'date_range_end must be on or after date_range_start.'}
            )
        if (end - start).days > 365:
            raise serializers.ValidationError('Date range cannot exceed 365 days.')
        return attrs


class DashboardQuerySerializer(serializers.Serializer):
    booking_page = serializers.IntegerField(min_value=1, default=1, required=False)
    chart_range = serializers.ChoiceField(
        choices=['week', 'month'], default='week', required=False
    )


class BookingItemSerializer(serializers.Serializer):
    # Single booking row in the dashboard booking list
    booking_id = serializers.CharField()
    date = serializers.DateField()
    passenger_name = serializers.CharField()
    vehicle_type = serializers.CharField(allow_null=True)
    plan = serializers.CharField()
    pickup_date = serializers.DateField()
    return_date = serializers.DateField(allow_null=True)
    payment_status = serializers.CharField()
    trip_status = serializers.CharField()
