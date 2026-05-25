from rest_framework import serializers
from .models import Conversation, Message, BroadcastMessage


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'sender_type', 'content', 'is_read', 'sent_at']


# Conversation list row — last message preview and unread count, no messages embedded
class ConversationListSerializer(serializers.ModelSerializer):
    conversation_id = serializers.UUIDField(source='id')
    driver_name = serializers.CharField(source='driver.full_name')
    driver_image = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'conversation_id', 'driver_name', 'driver_image',
            'last_message', 'last_message_at', 'unread_count',
        ]

    def get_driver_image(self, obj):
        request = self.context.get('request')
        if obj.driver.profile_picture and request:
            return request.build_absolute_uri(obj.driver.profile_picture.url)
        return None

    def get_last_message(self, obj):
        last = obj.messages.order_by('-sent_at').first()
        if last:
            return {'content': last.content, 'sent_at': last.sent_at}
        return None

    def get_unread_count(self, obj):
        return obj.messages.filter(is_read=False, sender_type='driver').count()


# Conversation detail — metadata only, no messages embedded
class ConversationMetaSerializer(serializers.ModelSerializer):
    conversation_id = serializers.UUIDField(source='id')
    driver_name = serializers.CharField(source='driver.full_name')
    driver_image = serializers.SerializerMethodField()
    provider_name = serializers.CharField(source='provider.business_name')
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'conversation_id', 'driver_name', 'driver_image',
            'provider_name', 'unread_count', 'last_message_at',
        ]

    def get_driver_image(self, obj):
        request = self.context.get('request')
        if obj.driver.profile_picture and request:
            return request.build_absolute_uri(obj.driver.profile_picture.url)
        return None

    def get_unread_count(self, obj):
        return obj.messages.filter(is_read=False, sender_type='driver').count()


class ConversationCreateSerializer(serializers.Serializer):
    driver_id = serializers.UUIDField()


class SendMessageSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=1000)

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError('Message content cannot be blank.')
        return value


class BroadcastSerializer(serializers.ModelSerializer):
    broadcast_id = serializers.UUIDField(source='id')

    class Meta:
        model = BroadcastMessage
        fields = ['broadcast_id', 'content', 'recipient_count', 'sent_at']


class BroadcastCreateSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=500)

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError('Broadcast content cannot be blank.')
        return value
