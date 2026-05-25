"""Profile, documents, vehicle, notifications, conversations views."""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.utils import timezone
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .auth import DriverJWTAuthentication
from .permissions import IsDriver
from .serializers import (
    DriverBasicProfileUpdateSerializer,
    DriverContactUpdateSerializer,
    DriverDocumentUploadSerializer,
)


class DriverBasicProfileView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        d = request.driver
        return CustomResponse.success(
            message='Profile fetched.',
            data={
                'full_name': d.full_name,
                'profile_picture': (
                    request.build_absolute_uri(d.profile_picture.url)
                    if d.profile_picture else None
                ),
                'total_trips': d.total_trips,
            },
            status_code=200
        )

    def patch(self, request):
        serializer = DriverBasicProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        d = request.driver
        data = serializer.validated_data
        if 'full_name' in data:
            d.full_name = data['full_name']
        if 'profile_picture' in data:
            d.profile_picture = data['profile_picture']
        d.save(update_fields=[k for k in data.keys()])

        return CustomResponse.success(
            message='Profile updated.',
            data={'full_name': d.full_name, 'total_trips': d.total_trips},
            status_code=200
        )


class DriverContactProfileView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        d = request.driver
        return CustomResponse.success(
            message='Contact info fetched.',
            data={
                'email': d.email,
                'phone_number': d.phone_number,
                'home_address': d.home_address,
            },
            status_code=200
        )

    def patch(self, request):
        serializer = DriverContactUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        d = request.driver
        data = serializer.validated_data
        if 'phone_number' in data:
            d.phone_number = data['phone_number']
        if 'home_address' in data:
            d.home_address = data['home_address']
        d.save(update_fields=[k for k in data.keys()])

        return CustomResponse.success(
            message='Contact info updated.',
            data={'email': d.email, 'phone_number': d.phone_number, 'home_address': d.home_address},
            status_code=200
        )


class DriverDocumentsView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        from apps.drivers.models import DriverDocument
        docs = DriverDocument.objects.filter(
            driver=request.driver
        ).order_by('expire_date')

        results = []
        for doc in docs:
            results.append({
                'document_type': doc.document_type,
                'document_number': None,
                'expire_date': doc.expire_date,
                'upload_date': doc.upload_date,
                'file_url': (
                    request.build_absolute_uri(doc.file.url) if doc.file else None
                ),
            })

        return CustomResponse.success(
            message='Documents fetched.',
            data={'documents': results},
            status_code=200
        )

    def post(self, request):
        serializer = DriverDocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        data = serializer.validated_data
        from apps.drivers.models import DriverDocument

        doc = DriverDocument.objects.create(
            driver=request.driver,
            document_type=data['document_type'],
            file=data['file'],
            expire_date=data.get('expire_date'),
        )

        # Register in compliance app
        try:
            from apps.compliance.utils import register_compliance_document
            register_compliance_document(
                provider=request.driver.provider,
                holder_type='driver',
                holder_id=str(request.driver.id),
                holder_name=request.driver.full_name,
                document_type=data['document_type'],
                document_number=data.get('document_number'),
                upload_date=timezone.now().date(),
                expiration_date=data.get('expire_date'),
                file_reference=(
                    request.build_absolute_uri(doc.file.url) if doc.file else ''
                ),
            )
        except Exception:
            pass

        return CustomResponse.success(
            message='Document uploaded.',
            data={
                'document_type': doc.document_type,
                'upload_date': doc.upload_date,
                'expire_date': doc.expire_date,
            },
            status_code=201
        )


class DriverVehicleUpdateView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        driver = request.driver
        if not driver.vehicle:
            return CustomResponse.error(
                'No vehicle assigned.',
                404
            )

        vehicle = driver.vehicle
        return CustomResponse.success(
            message='Vehicle fetched.',
            data={
                'vehicle_id': str(vehicle.id),
                'vehicle_name': f'{vehicle.brand} {vehicle.model_number}',
                'vehicle_number': vehicle.license_plate,
                'vehicle_type': vehicle.vehicle_type,
                'year': vehicle.year,
                'color': vehicle.color,
                'seating_capacity': vehicle.seating_capacity,
                'accessibility_features': vehicle.accessibility_features,
                'status': vehicle.status,
            },
            status_code=200
        )


class DriverNotificationPreferencesView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        from apps.notifications.utils import get_or_create_preference
        from apps.notifications.serializers import NotificationPreferenceSerializer
        pref = get_or_create_preference('driver', str(request.driver.id), request.driver.provider)
        return CustomResponse.success(
            message='Preferences fetched.',
            data=NotificationPreferenceSerializer(pref).data,
            status_code=200
        )

    def patch(self, request):
        from apps.notifications.utils import get_or_create_preference
        from apps.notifications.serializers import NotificationPreferenceSerializer
        pref = get_or_create_preference('driver', str(request.driver.id), request.driver.provider)
        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)
        serializer.save()
        return CustomResponse.success(message='Preferences updated.', data=serializer.data, status_code=200)


class DriverNotificationsView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        from apps.notifications.models import Notification
        from apps.notifications.serializers import NotificationSerializer

        qs = Notification.objects.filter(
            recipient_type='driver',
            recipient_id=request.driver.id,
        )
        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)

        serializer = NotificationSerializer(qs, many=True)
        return CustomResponse.success(
            message='Notifications fetched.',
            data={'results': serializer.data},
            status_code=200
        )


class DriverAnnouncementsView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        from apps.notifications.models import Notification
        from apps.notifications.serializers import NotificationSerializer

        qs = Notification.objects.filter(
            recipient_type='driver',
            recipient_id=request.driver.id,
            category='announcement',
        )
        serializer = NotificationSerializer(qs, many=True)
        return CustomResponse.success(
            message='Announcements fetched.',
            data={'results': serializer.data},
            status_code=200
        )


class DriverNotificationDeleteView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def delete(self, request, id):
        from apps.notifications.models import Notification
        notif = get_object_or_404(
            Notification,
            id=id,
            recipient_type='driver',
            recipient_id=request.driver.id,
        )
        notif.delete()
        return Response(status=204)


class DriverConversationsView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request):
        from apps.communication.models import Conversation, Message
        convs = Conversation.objects.filter(
            driver=request.driver
        ).select_related('provider').prefetch_related('messages').order_by('-last_message_at')

        results = []
        for conv in convs:
            last = conv.messages.order_by('-sent_at').first()
            unread = conv.messages.filter(sender_type='provider', is_read=False).count()
            results.append({
                'conversation_id': str(conv.id),
                'provider_name': conv.provider.business_name,
                'last_message': {'content': last.content, 'sent_at': last.sent_at} if last else None,
                'last_message_at': conv.last_message_at,
                'unread_count': unread,
            })

        return CustomResponse.success(message='Conversations fetched.', data={'results': results}, status_code=200)


class DriverConversationDetailView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def get(self, request, id):
        from apps.communication.models import Conversation, Message
        conv = get_object_or_404(Conversation, id=id, driver=request.driver)

        # Mark provider messages as read
        now = timezone.now()
        Message.objects.filter(
            conversation=conv, sender_type='provider', is_read=False
        ).update(is_read=True, read_at=now)

        messages = conv.messages.order_by('sent_at')
        from apps.communication.serializers import MessageSerializer
        return CustomResponse.success(
            message='Conversation fetched.',
            data={
                'conversation_id': str(conv.id),
                'messages': MessageSerializer(messages, many=True).data,
            },
            status_code=200
        )


class DriverSendMessageView(APIView):
    authentication_classes = [DriverJWTAuthentication]
    permission_classes = [IsDriver]

    def post(self, request, id):
        from apps.communication.models import Conversation, Message
        from apps.communication.serializers import SendMessageSerializer, MessageSerializer

        conv = get_object_or_404(Conversation, id=id, driver=request.driver)

        serializer = SendMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error('Validation failed.', 400, errors=serializer.errors)

        now = timezone.now()
        msg = Message.objects.create(
            conversation=conv,
            sender_type='driver',
            sender_id=request.driver.id,
            content=serializer.validated_data['content'],
        )
        conv.last_message_at = now
        conv.save(update_fields=['last_message_at'])

        # WS broadcast
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(f'chat_{conv.id}', {
                'type': 'chat_message',
                'message_id': str(msg.id),
                'sender_type': 'driver',
                'content': msg.content,
                'sent_at': msg.sent_at.isoformat(),
            })
        except Exception:
            pass

        # Notify provider
        try:
            from apps.notifications.utils import send_notification
            send_notification(
                recipient_type='provider',
                recipient_id=str(conv.provider.id),
                provider_id=str(conv.provider.id),
                title=f'New message from {request.driver.full_name}',
                message=msg.content[:100],
                category='driver',
                related_object_type='conversation',
                related_object_id=str(conv.id),
            )
        except Exception:
            pass

        return CustomResponse.success(
            message='Message sent.',
            data=MessageSerializer(msg).data,
            status_code=201
        )
