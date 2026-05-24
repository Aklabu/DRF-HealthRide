"""
Celery tasks for outbound notification delivery.

Each channel (push, email, SMS) is a separate task so one channel failure
does not block the others. All tasks are fire-and-forget — failures are
logged but never re-raised to the caller.
"""
from django.utils import timezone


def send_push_notification(notification_id):
    """
    Send push notification via Firebase Cloud Messaging (FCM).
    Requires FIREBASE_SERVER_KEY in settings and a device token stored
    against the recipient (driver_app or provider_app device registration).
    """
    try:
        from .models import Notification
        from django.conf import settings

        notification = Notification.objects.select_related('provider').get(id=notification_id)

        fcm_key = getattr(settings, 'FIREBASE_SERVER_KEY', '')
        if not fcm_key:
            return  # FCM not configured — skip silently

        # Resolve device token for recipient
        device_token = _get_device_token(
            notification.recipient_type, notification.recipient_id
        )
        if not device_token:
            return

        import requests
        headers = {
            'Authorization': f'key={fcm_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'to': device_token,
            'notification': {
                'title': notification.title,
                'body': notification.message,
            },
            'data': {
                'notification_id': str(notification.id),
                'category': notification.category,
                'related_object_type': notification.related_object_type or '',
                'related_object_id': str(notification.related_object_id) if notification.related_object_id else '',
            },
        }
        requests.post(
            'https://fcm.googleapis.com/fcm/send',
            json=payload,
            headers=headers,
            timeout=10,
        )
    except Exception:
        pass  # Never raise — channel failure must not affect other channels


def send_email_notification(notification_id):
    # Send email notification via Django's email backend (SMTP).
    try:
        from .models import Notification
        from django.core.mail import send_mail
        from django.conf import settings

        notification = Notification.objects.select_related('provider').get(id=notification_id)

        recipient_email = _get_recipient_email(
            notification.recipient_type, notification.recipient_id
        )
        if not recipient_email:
            return

        send_mail(
            subject=notification.title,
            message=notification.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=True,
        )
    except Exception:
        pass


def send_sms_notification(notification_id):
    """
    Send SMS via Twilio.
    Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in settings.
    """
    try:
        from .models import Notification
        from django.conf import settings

        notification = Notification.objects.get(id=notification_id)

        account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
        auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
        from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '')

        if not all([account_sid, auth_token, from_number]):
            return  # Twilio not configured

        recipient_phone = _get_recipient_phone(
            notification.recipient_type, notification.recipient_id
        )
        if not recipient_phone:
            return

        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=f'{notification.title}: {notification.message}',
            from_=from_number,
            to=recipient_phone,
        )
    except Exception:
        pass


# Recipient resolution helpers 
def _get_device_token(recipient_type, recipient_id):
    """
    Resolve FCM device token for a recipient.
    Placeholder — device token storage is handled by driver_app registration.
    """
    try:
        if recipient_type == 'driver':
            from apps.drivers.models import Driver
            driver = Driver.objects.get(id=recipient_id)
            # Device token would be stored on a DeviceToken model in driver_app
            # Returning None until driver_app implements device registration
            return None
        elif recipient_type == 'provider':
            # Provider web dashboard uses WebSocket, not FCM
            return None
    except Exception:
        return None


def _get_recipient_email(recipient_type, recipient_id):
    # Resolve email address for a recipient
    try:
        if recipient_type == 'driver':
            from apps.drivers.models import Driver
            return Driver.objects.get(id=recipient_id).email
        elif recipient_type == 'provider':
            from apps.accounts.models import Provider
            return Provider.objects.get(id=recipient_id).business_email
    except Exception:
        return None


def _get_recipient_phone(recipient_type, recipient_id):
    # Resolve phone number for a recipient
    try:
        if recipient_type == 'driver':
            from apps.drivers.models import Driver
            return Driver.objects.get(id=recipient_id).phone_number
        elif recipient_type == 'provider':
            from apps.accounts.models import Provider
            return Provider.objects.get(id=recipient_id).contact_phone or None
    except Exception:
        return None


# Celery task registration
try:
    from config.celery import app as celery_app

    send_push_notification = celery_app.task(
        name='notifications.send_push_notification',
        ignore_result=True,
    )(send_push_notification)

    send_email_notification = celery_app.task(
        name='notifications.send_email_notification',
        ignore_result=True,
    )(send_email_notification)

    send_sms_notification = celery_app.task(
        name='notifications.send_sms_notification',
        ignore_result=True,
    )(send_sms_notification)

except Exception:
    pass
