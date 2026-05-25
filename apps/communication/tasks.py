# Celery tasks for the communication app
# broadcast_notify_drivers — fans out per-driver notifications for a broadcast
# Called immediately after BroadcastMessage is created so the HTTP response
# returns without waiting for potentially hundreds of notification calls


def broadcast_notify_drivers(broadcast_id):
    # For each active driver under the broadcast's provider:
    # 1. Send a push notification via the notifications app
    # 2. Push a broadcast.received event to each driver's notification WS group
    try:
        from .models import BroadcastMessage
        from apps.notifications.utils import send_notification
        from apps.drivers.models import Driver
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        broadcast = BroadcastMessage.objects.select_related('provider').get(id=broadcast_id)
        channel_layer = get_channel_layer()

        drivers = Driver.objects.filter(
            provider=broadcast.provider,
            status_employment='active',
        ).only('id', 'provider_id')

        for driver in drivers:
            try:
                send_notification(
                    recipient_type='driver',
                    recipient_id=str(driver.id),
                    provider_id=str(broadcast.provider.id),
                    title='Announcement from your provider',
                    message=broadcast.content,
                    category='announcement',
                    related_object_type='broadcast',
                    related_object_id=str(broadcast.id),
                )
            except Exception:
                pass

            # Push broadcast.received to the driver's notification WS group
            # Drivers share the provider's notification group keyed by provider_id
            try:
                async_to_sync(channel_layer.group_send)(
                    f'notifications.{broadcast.provider.id}',
                    {
                        'type': 'broadcast_received',
                        'content': broadcast.content,
                    }
                )
            except Exception:
                pass

    except Exception:
        pass


def push_conversation_new(conversation_id):
    # Push a conversation.new event to the provider's notification WS group
    # Called when a driver sends the first message in a new conversation
    try:
        from .models import Conversation
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        conv = Conversation.objects.select_related('provider', 'driver').get(id=conversation_id)
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            f'notifications.{conv.provider.id}',
            {
                'type': 'conversation_new',
                'conversation_id': str(conv.id),
                'driver_name': conv.driver.full_name,
            }
        )
    except Exception:
        pass


# Celery task registration 

try:
    from config.celery import app as celery_app

    broadcast_notify_drivers = celery_app.task(
        name='communication.broadcast_notify_drivers',
        ignore_result=True,
    )(broadcast_notify_drivers)

    push_conversation_new = celery_app.task(
        name='communication.push_conversation_new',
        ignore_result=True,
    )(push_conversation_new)

except Exception:
    pass
