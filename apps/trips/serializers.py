from rest_framework import serializers
from django.utils import timezone
from .models import Trip, TripPassengerContact, TripStatusLog


# Validate and parse passenger information from trip creation request
class PassengerInputSerializer(serializers.Serializer):
    fullName = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)
    relation = serializers.ChoiceField(
        choices=['self', 'father', 'mother', 'other'], default='other'
    )
    homeAddress = serializers.CharField(required=False, allow_blank=True)


# Validate pickup location, date, time, and special requirements
class PickupInputSerializer(serializers.Serializer):
    address = serializers.CharField()
    dropAddress = serializers.CharField()
    date = serializers.DateField()
    time = serializers.TimeField()
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    specialRequirement = serializers.ChoiceField(
        choices=['standard', 'wheelchair', 'stretcher', 'oxygen']
    )

    def validate_date(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError('Pickup date cannot be in the past.')
        return value


# Validate trip type, passenger, and pickup details for trip creation
class TripCreateSerializer(serializers.Serializer):
    tripType = serializers.ChoiceField(choices=['single', 'recurring'])
    passenger = PassengerInputSerializer()
    pickup = PickupInputSerializer()


# Validate driver assignment, authorization, and payment information
class AssignDriverSerializer(serializers.Serializer):
    driverId = serializers.UUIDField(required=False, allow_null=True)
    authorizationNumber = serializers.CharField()
    medicalNotes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    paymentMethod = serializers.ChoiceField(
        choices=['cash', 'card', 'insurance', 'send_link', 'payment_later']
    )
    paymentDelivery = serializers.ChoiceField(
        choices=['sms', 'email'], required=False, allow_null=True
    )

    def validate(self, attrs):
        if attrs.get('paymentMethod') == 'send_link' and not attrs.get('paymentDelivery'):
            raise serializers.ValidationError(
                {'paymentDelivery': 'paymentDelivery is required when paymentMethod is send_link.'}
            )
        return attrs


# Validate trip confirmation or cancellation action
class TripConfirmSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['confirm', 'cancel'])


# Serialize trip status log entries for audit trail
class TripStatusLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripStatusLog
        fields = ['from_status', 'to_status', 'changed_at', 'changed_by', 'notes']
