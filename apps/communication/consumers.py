import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


def _parse_token(scope):
    # Extract ?token= from WebSocket query string
    query_string = scope.get('query_string', b'').decode()
    params = dict(p.split('=') for p in query_string.split('&') if '=' in p)
    return params.get('token', '')


@database_sync_to_async
def _resolve_identity(token):
    # Validate JWT and return (sender_type, sender_id, provider_id) or None
    try:
        from rest_framework_simplejwt.tokens import AccessToken

        decoded = AccessToken(token)

        # Driver token carries driver_id claim (set by driver_app at login)
        driver_id = decoded.get('driver_id')
        if driver_id:
            from apps.drivers.models import Driver
            driver = Driver.objects.select_related('provider').get(id=driver_id)
            return 'driver', str(driver.id), str(driver.provider.id)

        # Provider token uses standard user_id claim
        user_id = decoded.get('user_id')
        if user_id:
            from apps.accounts.models import Provider
            provider = Provider.objects.get(id=user_id, is_active=True)
            return 'provider', str(provider.id), str(provider.id)

    except Exception:
        pass
    return None


@database_sync_to_async
def _get_conversation(conversation_id, sender_type, sender_id):
    # Fetch Conversation and validate the requester is a participant
    try:
        from .models import Conversation
        conv = Conversation.objects.select_related('provider', 'driver').get(
            id=conversation_id
        )
        if sender_type == 'provider' and str(conv.provider.id) == sender_id:
            return conv
        if sender_type == 'driver' and str(conv.driver.id) == sender_id:
            return conv
    except Exception:
        pass
    return None


@database_sync_to_async
def _persist_message(conversation, sender_type, sender_id, content):
    # Save message to DB and update conversation.last_message_at
    from .models import Message
    now = timezone.now()
    msg = Message.objects.create(
        conversation=conversation,
        sender_type=sender_type,
        sender_id=sender_id,
        content=content,
    )
    conversation.last_message_at = now
    conversation.save(update_fields=['last_message_at'])
    return msg


@database_sync_to_async
def _mark_message_read(message_id, conversation, reader_type):
    # Mark a specific message as read if the reader is the recipient
    from .models import Message
    try:
        msg = Message.objects.get(id=message_id, conversation=conversation)
        # Only the recipient can mark a message as read
        if msg.sender_type != reader_type and not msg.is_read:
            msg.is_read = True
            msg.read_at = timezone.now()
            msg.save(update_fields=['is_read', 'read_at'])
            return str(msg.id)
    except Message.DoesNotExist:
        pass
    return None


@database_sync_to_async
def _notify_other_party(conversation, sender_type, message):
    # Send push notification to the party that didn't send the message
    try:
        from apps.notifications.utils import send_notification
        if sender_type == 'provider':
            send_notification(
                recipient_type='driver',
                recipient_id=str(conversation.driver.id),
                provider_id=str(conversation.provider.id),
                title=f'New message from {conversation.provider.business_name}',
                message=message.content[:100],
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
                message=message.content[:100],
                category='driver',
                related_object_type='conversation',
                related_object_id=str(conversation.id),
            )
    except Exception:
        pass


# ── ChatConsumer ──────────────────────────────────────────────────────────────
# Real-time chat stream for a single conversation
# WS: ws://communication/chat/{conversation_id}/?token=<jwt>
#
# Supported client → server event types:
#   message.send   — send a new message
#   typing.start   — notify the other party you are typing
#   typing.stop    — notify the other party you stopped typing
#   message.read   — mark a specific message as read
#
# Server → client event types:
#   message.new         — a new message was sent by either party
#   typing.indicator    — the other party's typing state changed
#   message.read_ack    — a message was marked as read
#   error               — validation or protocol error with a code

class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        token = _parse_token(self.scope)
        identity = await _resolve_identity(token)

        if not identity:
            await self.close(code=4001)
            return

        self.sender_type, self.sender_id, self.provider_id = identity
        conversation_id = self.scope['url_route']['kwargs'].get('conversation_id')

        self.conversation = await _get_conversation(
            conversation_id, self.sender_type, self.sender_id
        )

        if not self.conversation:
            await self.close(code=4004)
            return

        self.chat_group = f'chat_{conversation_id}'
        await self.accept()
        await self.channel_layer.group_add(self.chat_group, self.channel_name)

    async def receive(self, text_data):
        try:
            frame = json.loads(text_data)
        except (json.JSONDecodeError, ValueError):
            await self.send(text_data=json.dumps({
                'type': 'error', 'code': 'INVALID_JSON', 'message': 'Invalid JSON.'
            }))
            return

        event_type = frame.get('type', '')

        if event_type == 'message.send':
            await self._handle_message_send(frame)

        elif event_type == 'typing.start':
            await self._handle_typing(is_typing=True)

        elif event_type == 'typing.stop':
            await self._handle_typing(is_typing=False)

        elif event_type == 'message.read':
            await self._handle_message_read(frame)

        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'code': 'UNKNOWN_EVENT',
                'message': f'Unknown event type: {event_type}',
            }))

    async def disconnect(self, close_code):
        if hasattr(self, 'chat_group'):
            await self.channel_layer.group_discard(self.chat_group, self.channel_name)

    # Event handlers

    async def _handle_message_send(self, frame):
        content = frame.get('content', '').strip()

        if not content:
            await self.send(text_data=json.dumps({
                'type': 'error', 'code': 'BLANK_CONTENT', 'message': 'Content cannot be blank.'
            }))
            return

        if len(content) > 1000:
            await self.send(text_data=json.dumps({
                'type': 'error', 'code': 'MSG_TOO_LONG', 'message': 'Max 1000 chars.'
            }))
            return

        message = await _persist_message(
            self.conversation, self.sender_type, self.sender_id, content
        )

        # If this is the first message in the conversation, notify the provider dashboard
        is_first = await self._is_first_message()
        if is_first and self.sender_type == 'driver':
            try:
                from .tasks import push_conversation_new
                push_conversation_new.delay(str(self.conversation.id))
            except Exception:
                pass

        # Broadcast new message to both parties in the conversation group
        await self.channel_layer.group_send(self.chat_group, {
            'type': 'chat_message_new',
            'message_id': str(message.id),
            'sender_type': self.sender_type,
            'content': content,
            'sent_at': message.sent_at.isoformat(),
        })

        # Push notification to the other party's other devices
        await _notify_other_party(self.conversation, self.sender_type, message)

        # Also push unread count update to the provider's notification WS group
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            from apps.communication.models import Message as Msg
            channel_layer = get_channel_layer()
            unread = await self._get_provider_unread_count()
            await self.channel_layer.group_send(
                f'notifications.{self.provider_id}',
                {'type': 'unread_update', 'count': unread}
            )
        except Exception:
            pass

    async def _handle_typing(self, is_typing):
        # Broadcast typing indicator to the other party only
        await self.channel_layer.group_send(self.chat_group, {
            'type': 'chat_typing',
            'sender_type': self.sender_type,
            'is_typing': is_typing,
        })

    async def _handle_message_read(self, frame):
        message_id = frame.get('message_id', '')
        if not message_id:
            await self.send(text_data=json.dumps({
                'type': 'error', 'code': 'MISSING_FIELD', 'message': 'message_id is required.'
            }))
            return

        acked_id = await _mark_message_read(
            message_id, self.conversation, self.sender_type
        )

        if acked_id:
            # Notify the sender that their message was read
            await self.channel_layer.group_send(self.chat_group, {
                'type': 'chat_read_ack',
                'message_id': acked_id,
            })

    @database_sync_to_async
    def _get_provider_unread_count(self):
        from apps.communication.models import Message as Msg
        return Msg.objects.filter(
            conversation__provider_id=self.provider_id,
            is_read=False,
            sender_type='driver',
        ).count()

    @database_sync_to_async
    def _is_first_message(self):
        # Returns True if the conversation has exactly one message (the one just created)
        from apps.communication.models import Message as Msg
        return Msg.objects.filter(conversation=self.conversation).count() == 1

    # Channel layer message handlers 

    async def chat_message_new(self, event):
        # Forward new message to this WebSocket connection
        await self.send(text_data=json.dumps({
            'type': 'message.new',
            'message_id': event['message_id'],
            'sender_type': event['sender_type'],
            'content': event['content'],
            'sent_at': event['sent_at'],
        }))

    async def chat_typing(self, event):
        # Forward typing indicator — skip if it's from the same sender (don't echo back)
        if event['sender_type'] != self.sender_type:
            await self.send(text_data=json.dumps({
                'type': 'typing.indicator',
                'sender_type': event['sender_type'],
                'is_typing': event['is_typing'],
            }))

    async def chat_read_ack(self, event):
        # Forward read acknowledgement to this connection
        await self.send(text_data=json.dumps({
            'type': 'message.read_ack',
            'message_id': event['message_id'],
        }))


# NotificationConsumer 
# Dashboard-level real-time updates — replaces polling GET /api/communication/
# WS: ws://notifications/?token=<jwt>
#
# Server → client event types:
#   unread.update        — total unread message count changed
#   conversation.new     — a new conversation was started by a driver
#   broadcast.received   — a broadcast was sent (driver-side only)

class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        token = _parse_token(self.scope)
        identity = await _resolve_identity(token)

        if not identity:
            await self.close(code=4001)
            return

        self.sender_type, self.sender_id, self.provider_id = identity

        # Each provider has their own notification group
        self.notif_group = f'notifications.{self.provider_id}'
        await self.accept()
        await self.channel_layer.group_add(self.notif_group, self.channel_name)

        # Send current unread count immediately on connect
        unread = await self._get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'unread.update',
            'count': unread,
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'notif_group'):
            await self.channel_layer.group_discard(self.notif_group, self.channel_name)

    # Channel layer message handlers 

    async def unread_update(self, event):
        # Push updated unread message count to the dashboard
        await self.send(text_data=json.dumps({
            'type': 'unread.update',
            'count': event.get('count', 0),
        }))

    async def conversation_new(self, event):
        # Notify dashboard that a new conversation was started
        await self.send(text_data=json.dumps({
            'type': 'conversation.new',
            'conversation_id': event.get('conversation_id'),
            'driver_name': event.get('driver_name'),
        }))

    async def broadcast_received(self, event):
        # Notify driver app that a broadcast was received
        await self.send(text_data=json.dumps({
            'type': 'broadcast.received',
            'content': event.get('content'),
        }))

    @database_sync_to_async
    def _get_unread_count(self):
        from apps.communication.models import Message
        return Message.objects.filter(
            conversation__provider_id=self.provider_id,
            is_read=False,
            sender_type='driver',
        ).count()
