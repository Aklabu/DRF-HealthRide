import base64
import json
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import timedelta

from utils.response import CustomResponse
from .models import Conversation, Message, BroadcastMessage
from .serializers import (
    ConversationListSerializer,
    ConversationMetaSerializer,
    MessageSerializer,
    SendMessageSerializer,
    BroadcastSerializer,
    BroadcastCreateSerializer,
    ConversationCreateSerializer,
)

PAGE_SIZE = 20  # conversations per page
MSG_PAGE_SIZE = 30  # messages per page


def _get_requester(request):
    # Derive (requester_type, requester_id) from the authenticated token
    token = getattr(request, 'auth', None)
    if token and hasattr(token, 'payload'):
        driver_id = token.payload.get('driver_id')
        if driver_id:
            return 'driver', str(driver_id)
    return 'provider', str(request.user.id)


def _get_conversation_for_requester(conversation_id, requester_type, requester_id):
    # Fetch Conversation and validate the requester is the provider or driver on it
    try:
        conv = Conversation.objects.select_related('provider', 'driver').get(
            id=conversation_id
        )
        if requester_type == 'provider' and str(conv.provider.id) == requester_id:
            return conv
        if requester_type == 'driver' and str(conv.driver.id) == requester_id:
            return conv
    except Conversation.DoesNotExist:
        pass
    from django.http import Http404
    raise Http404


def _encode_cursor(message_id):
    # Encode a message UUID as a base64 cursor string
    return base64.urlsafe_b64encode(str(message_id).encode()).decode()


def _decode_cursor(cursor):
    # Decode a base64 cursor back to a message UUID string, or None if invalid
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception:
        return None


# Header Stats 

class CommunicationStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        cutoff = now - timedelta(hours=24)

        unread_messages = Message.objects.filter(
            conversation__provider=request.user,
            is_read=False,
            sender_type='driver',
        ).count()

        active_conversations = Conversation.objects.filter(
            provider=request.user,
            last_message_at__gte=cutoff,
        ).count()

        total_broadcasts_sent = BroadcastMessage.objects.filter(
            provider=request.user
        ).count()

        return CustomResponse.success(
            message='Communication stats fetched.',
            data={
                'unread_messages': unread_messages,
                'active_conversations': active_conversations,
                'total_broadcasts_sent': total_broadcasts_sent,
            },
            status_code=200
        )


# Conversations 

class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Cursor-based pagination — cursor encodes the last conversation's id
        cursor = request.query_params.get('cursor')
        qs = Conversation.objects.filter(
            provider=request.user
        ).select_related('driver').prefetch_related('messages').order_by(
            '-last_message_at', '-created_at'
        )

        if cursor:
            decoded = _decode_cursor(cursor)
            if decoded:
                try:
                    pivot = Conversation.objects.get(id=decoded, provider=request.user)
                    qs = qs.filter(
                        last_message_at__lt=pivot.last_message_at
                    ) | qs.filter(
                        last_message_at=pivot.last_message_at,
                        created_at__lt=pivot.created_at,
                    )
                    qs = qs.filter(provider=request.user).order_by(
                        '-last_message_at', '-created_at'
                    )
                except Conversation.DoesNotExist:
                    pass

        page = list(qs[:PAGE_SIZE + 1])
        has_next = len(page) > PAGE_SIZE
        results = page[:PAGE_SIZE]

        next_cursor = None
        if has_next and results:
            next_cursor = _encode_cursor(results[-1].id)

        serializer = ConversationListSerializer(
            results, many=True, context={'request': request}
        )
        return CustomResponse.success(
            message='Conversations fetched.',
            data={
                'next_cursor': next_cursor,
                'results': serializer.data,
            },
            status_code=200
        )

    def post(self, request):
        # Create a new conversation between this provider and a driver
        serializer = ConversationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        driver_id = serializer.validated_data['driver_id']

        from apps.drivers.models import Driver
        try:
            driver = Driver.objects.get(id=driver_id, provider=request.user)
        except Driver.DoesNotExist:
            return CustomResponse.error(
                message='Driver not found or does not belong to your account.',
                status_code=404
            )

        # Return existing conversation if one already exists — no duplicates
        existing = Conversation.objects.filter(
            provider=request.user, driver=driver
        ).first()

        if existing:
            return CustomResponse.success(
                message='Conversation already exists.',
                data={'conversation_id': str(existing.id)},
                status_code=200
            )

        conversation = Conversation.objects.create(
            provider=request.user,
            driver=driver,
        )

        driver_image = None
        if driver.profile_picture:
            driver_image = request.build_absolute_uri(driver.profile_picture.url)

        return CustomResponse.success(
            message='Conversation created.',
            data={
                'conversation_id': str(conversation.id),
                'driver_name': driver.full_name,
                'driver_image': driver_image,
            },
            status_code=201
        )


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        requester_type, requester_id = _get_requester(request)
        conversation = _get_conversation_for_requester(id, requester_type, requester_id)

        # Mark messages from the other party as read
        opposite_type = 'driver' if requester_type == 'provider' else 'provider'
        now = timezone.now()
        Message.objects.filter(
            conversation=conversation,
            sender_type=opposite_type,
            is_read=False,
        ).update(is_read=True, read_at=now)

        # Push unread count update to the requester's notification WS
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            provider_id = str(conversation.provider.id)
            unread_total = Message.objects.filter(
                conversation__provider_id=provider_id,
                is_read=False,
                sender_type='driver',
            ).count()
            async_to_sync(channel_layer.group_send)(
                f'notifications.{provider_id}',
                {'type': 'unread_update', 'count': unread_total}
            )
        except Exception:
            pass

        # Return metadata only — messages are fetched separately with pagination
        serializer = ConversationMetaSerializer(
            conversation, context={'request': request}
        )
        return CustomResponse.success(
            message='Conversation fetched.',
            data=serializer.data,
            status_code=200
        )


# Messages 

class MessageListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        requester_type, requester_id = _get_requester(request)
        conversation = _get_conversation_for_requester(id, requester_type, requester_id)

        qs = Message.objects.filter(
            conversation=conversation
        ).order_by('-sent_at')

        # Cursor-based pagination — cursor encodes the last message's id
        cursor = request.query_params.get('cursor')
        if cursor:
            decoded = _decode_cursor(cursor)
            if decoded:
                try:
                    pivot = Message.objects.get(id=decoded, conversation=conversation)
                    qs = qs.filter(sent_at__lt=pivot.sent_at)
                except Message.DoesNotExist:
                    pass

        # after= param for reconnection catch-up — fetch messages after a known id
        after = request.query_params.get('after')
        if after:
            try:
                pivot = Message.objects.get(id=after, conversation=conversation)
                qs = Message.objects.filter(
                    conversation=conversation,
                    sent_at__gt=pivot.sent_at,
                ).order_by('sent_at')
                serializer = MessageSerializer(qs, many=True)
                return CustomResponse.success(
                    message='Messages fetched.',
                    data={'next_cursor': None, 'results': serializer.data},
                    status_code=200
                )
            except Message.DoesNotExist:
                pass

        page = list(qs[:MSG_PAGE_SIZE + 1])
        has_next = len(page) > MSG_PAGE_SIZE
        results = page[:MSG_PAGE_SIZE]

        # Return in chronological order for rendering
        results = list(reversed(results))

        next_cursor = None
        if has_next and page:
            next_cursor = _encode_cursor(page[MSG_PAGE_SIZE - 1].id)

        serializer = MessageSerializer(results, many=True)
        return CustomResponse.success(
            message='Messages fetched.',
            data={
                'next_cursor': next_cursor,
                'results': serializer.data,
            },
            status_code=200
        )


class SendMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        requester_type, requester_id = _get_requester(request)
        conversation = _get_conversation_for_requester(id, requester_type, requester_id)

        serializer = SendMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        content = serializer.validated_data['content']
        now = timezone.now()

        with transaction.atomic():
            message = Message.objects.create(
                conversation=conversation,
                sender_type=requester_type,
                sender_id=requester_id,
                content=content,
            )
            conversation.last_message_at = now
            conversation.save(update_fields=['last_message_at'])

        # Broadcast via WebSocket to both parties in the chat group
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(f'chat_{conversation.id}', {
                'type': 'chat_message',
                'message_id': str(message.id),
                'sender_type': requester_type,
                'content': content,
                'sent_at': message.sent_at.isoformat(),
            })
        except Exception:
            pass

        # Push notification to the other party
        try:
            from apps.notifications.utils import send_notification
            if requester_type == 'provider':
                send_notification(
                    recipient_type='driver',
                    recipient_id=str(conversation.driver.id),
                    provider_id=str(conversation.provider.id),
                    title=f'New message from {conversation.provider.business_name}',
                    message=content[:100],
                    category='driver',
                    related_object_type='conversation',
                    related_object_id=str(conversation.id),
                )
            else:
                send_notification(
                    recipient_type='provider',
                    recipient_id=str(conversation.provider.id),
                    provider_id=str(conversation.provider.id),
                    title=f'New message from {conversation.driver.full_name}',
                    message=content[:100],
                    category='driver',
                    related_object_type='conversation',
                    related_object_id=str(conversation.id),
                )
        except Exception:
            pass

        return CustomResponse.success(
            message='Message sent.',
            data=MessageSerializer(message).data,
            status_code=201
        )


# Broadcast 

class BroadcastView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        broadcasts = BroadcastMessage.objects.filter(
            provider=request.user
        ).order_by('-sent_at')

        serializer = BroadcastSerializer(broadcasts, many=True)
        return CustomResponse.success(
            message='Broadcast history fetched.',
            data={'results': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = BroadcastCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        content = serializer.validated_data['content']

        from apps.drivers.models import Driver
        recipient_count = Driver.objects.filter(
            provider=request.user,
            status_employment='active',
        ).count()

        broadcast = BroadcastMessage.objects.create(
            provider=request.user,
            content=content,
            recipient_count=recipient_count,
        )

        # Fan out notifications async via Celery
        try:
            from .tasks import broadcast_notify_drivers
            broadcast_notify_drivers.delay(str(broadcast.id))
        except Exception:
            try:
                from .tasks import broadcast_notify_drivers as sync_fn
                sync_fn(str(broadcast.id))
            except Exception:
                pass

        response_serializer = BroadcastSerializer(broadcast)
        return CustomResponse.success(
            message='Broadcast sent.',
            data=response_serializer.data,
            status_code=201
        )
