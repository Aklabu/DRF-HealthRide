from rest_framework import serializers
from .models import NotificationPreference, NotificationTemplate, Notification
from .utils import validate_placeholders, SUPPORTED_PLACEHOLDERS


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'message', 'category',
            'related_object_type', 'related_object_id',
            'is_read', 'read_at', 'created_at',
        ]


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            'trip_updates', 'driver_alerts', 'passenger_messages',
            'financial_alerts', 'announcements',
            'push_enabled', 'email_enabled', 'sms_enabled',
        ]

    def validate(self, attrs):
        # Determine final channel states (merge with existing if partial update)
        instance = self.instance
        push = attrs.get('push_enabled', instance.push_enabled if instance else True)
        email = attrs.get('email_enabled', instance.email_enabled if instance else True)
        sms = attrs.get('sms_enabled', instance.sms_enabled if instance else False)

        if not any([push, email, sms]):
            raise serializers.ValidationError(
                'At least one notification channel (push, email, or SMS) must remain enabled.'
            )
        return attrs


class NotificationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'template_name', 'category',
            'subject', 'content', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_at']


class NotificationTemplateCreateSerializer(serializers.Serializer):
    template_name = serializers.CharField(max_length=255)
    category = serializers.ChoiceField(
        choices=['trip', 'driver', 'payment', 'announcement', 'compliance']
    )
    subject = serializers.CharField(max_length=255)
    content = serializers.CharField()

    def validate_content(self, value):
        unsupported = validate_placeholders(value)
        if unsupported:
            raise serializers.ValidationError(
                f'Unsupported placeholders: {", ".join(unsupported)}. '
                f'Supported: {", ".join(sorted(SUPPORTED_PLACEHOLDERS))}.'
            )
        return value

    def validate_template_name(self, value):
        # Uniqueness check is done in the view with provider context
        return value


class NotificationTemplateUpdateSerializer(serializers.Serializer):
    template_name = serializers.CharField(max_length=255, required=False)
    category = serializers.ChoiceField(
        choices=['trip', 'driver', 'payment', 'announcement', 'compliance'],
        required=False
    )
    subject = serializers.CharField(max_length=255, required=False)
    content = serializers.CharField(required=False)

    def validate_content(self, value):
        unsupported = validate_placeholders(value)
        if unsupported:
            raise serializers.ValidationError(
                f'Unsupported placeholders: {", ".join(unsupported)}. '
                f'Supported: {", ".join(sorted(SUPPORTED_PLACEHOLDERS))}.'
            )
        return value
