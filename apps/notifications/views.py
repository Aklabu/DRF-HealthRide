from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.shortcuts import get_object_or_404

from utils.response import CustomResponse
from .models import NotificationPreference, NotificationTemplate, Notification
from .serializers import (
    NotificationSerializer,
    NotificationPreferenceSerializer,
    NotificationTemplateSerializer,
    NotificationTemplateCreateSerializer,
    NotificationTemplateUpdateSerializer,
)
from .utils import (
    get_or_create_preference,
    invalidate_unread_cache,
    get_cached_unread_count,
    set_cached_unread_count,
)


def _get_recipient(request):
    """
    Derive recipient_type and recipient_id from the authenticated user.
    Providers authenticate as Provider; drivers authenticate via driver_app JWT
    which sets a 'driver_id' claim in the token payload.
    """
    # Check if this is a driver token (driver_app sets driver_id in JWT payload)
    token = getattr(request, 'auth', None)
    if token and hasattr(token, 'payload'):
        driver_id = token.payload.get('driver_id')
        if driver_id:
            return 'driver', str(driver_id)

    # Default: provider
    return 'provider', str(request.user.id)


# Notification Inbox 
class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        recipient_type, recipient_id = _get_recipient(request)

        qs = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
        )

        # Optional filters
        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)

        is_read = request.query_params.get('is_read')
        if is_read is not None:
            qs = qs.filter(is_read=is_read.lower() == 'true')

        unread_count = qs.filter(is_read=False).count()

        serializer = NotificationSerializer(qs, many=True)
        return CustomResponse.success(
            message='Notifications fetched.',
            data={
                'unread_count': unread_count,
                'results': serializer.data,
            },
            status_code=200
        )


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        recipient_type, recipient_id = _get_recipient(request)

        notification = get_object_or_404(
            Notification,
            id=id,
            recipient_type=recipient_type,
            recipient_id=recipient_id,
        )

        # Idempotent — no-op if already read
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])
            invalidate_unread_cache(recipient_type, recipient_id)

        serializer = NotificationSerializer(notification)
        return CustomResponse.success(
            message='Notification marked as read.',
            data=serializer.data,
            status_code=200
        )


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        recipient_type, recipient_id = _get_recipient(request)

        now = timezone.now()
        updated = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            is_read=False,
        ).update(is_read=True, read_at=now)

        invalidate_unread_cache(recipient_type, recipient_id)

        return CustomResponse.success(
            message='All notifications marked as read.',
            data={'updated_count': updated},
            status_code=200
        )


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        recipient_type, recipient_id = _get_recipient(request)

        # Try cache first
        cached = get_cached_unread_count(recipient_type, recipient_id)
        if cached is not None:
            return CustomResponse.success(
                message='Unread count fetched.',
                data={'unread_count': cached},
                status_code=200
            )

        count = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            is_read=False,
        ).count()

        set_cached_unread_count(recipient_type, recipient_id, count)

        return CustomResponse.success(
            message='Unread count fetched.',
            data={'unread_count': count},
            status_code=200
        )


# Users Notification Preferences 
class NotificationPreferenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        recipient_type, recipient_id = _get_recipient(request)
        pref = get_or_create_preference(recipient_type, recipient_id, request.user)
        serializer = NotificationPreferenceSerializer(pref)
        return CustomResponse.success(
            message='Preferences fetched.',
            data=serializer.data,
            status_code=200
        )

    def patch(self, request):
        recipient_type, recipient_id = _get_recipient(request)
        pref = get_or_create_preference(recipient_type, recipient_id, request.user)

        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )
        serializer.save()
        return CustomResponse.success(
            message='Preferences updated.',
            data=serializer.data,
            status_code=200
        )


# Templates for Notification
class NotificationTemplateListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = NotificationTemplate.objects.filter(
            provider=request.user, is_active=True
        )

        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)

        qs = qs.order_by('-created_at')
        serializer = NotificationTemplateSerializer(qs, many=True)
        return CustomResponse.success(
            message='Templates fetched.',
            data={'templates': serializer.data},
            status_code=200
        )

    def post(self, request):
        serializer = NotificationTemplateCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Validate template_name unique within provider (case-insensitive)
        if NotificationTemplate.objects.filter(
            provider=request.user,
            template_name__iexact=data['template_name'],
            is_active=True,
        ).exists():
            return CustomResponse.error(
                message='A template with this name already exists.',
                status_code=400
            )

        template = NotificationTemplate.objects.create(
            provider=request.user,
            template_name=data['template_name'],
            category=data['category'],
            subject=data['subject'],
            content=data['content'],
        )

        response_serializer = NotificationTemplateSerializer(template)
        return CustomResponse.success(
            message='Template created.',
            data=response_serializer.data,
            status_code=201
        )


class NotificationTemplateDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        template = get_object_or_404(
            NotificationTemplate,
            id=id,
            provider=request.user,
            is_active=True,
        )

        serializer = NotificationTemplateUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return CustomResponse.error(
                message='Validation failed.',
                status_code=400,
                errors=serializer.errors
            )

        data = serializer.validated_data

        # Re-validate name uniqueness if changing template_name
        new_name = data.get('template_name')
        if new_name and new_name.lower() != template.template_name.lower():
            if NotificationTemplate.objects.filter(
                provider=request.user,
                template_name__iexact=new_name,
                is_active=True,
            ).exclude(id=template.id).exists():
                return CustomResponse.error(
                    message='A template with this name already exists.',
                    status_code=400
                )

        for field, value in data.items():
            setattr(template, field, value)
        template.save()

        response_serializer = NotificationTemplateSerializer(template)
        return CustomResponse.success(
            message='Template updated.',
            data=response_serializer.data,
            status_code=200
        )

    def delete(self, request, id):
        template = get_object_or_404(
            NotificationTemplate,
            id=id,
            provider=request.user,
            is_active=True,
        )
        template.is_active = False
        template.save(update_fields=['is_active'])
        return Response(status=204)
