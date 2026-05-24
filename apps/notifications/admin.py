from django.contrib import admin
from .models import NotificationPreference, NotificationTemplate, Notification


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = [
        'recipient_type', 'recipient_id', 'provider',
        'push_enabled', 'email_enabled', 'sms_enabled',
    ]
    list_filter = ['recipient_type', 'push_enabled', 'email_enabled', 'sms_enabled']
    search_fields = ['provider__business_email']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ['template_name', 'category', 'provider', 'is_active', 'created_at']
    list_filter = ['category', 'is_active']
    search_fields = ['template_name', 'provider__business_email']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'category', 'recipient_type', 'recipient_id',
        'is_read', 'created_at',
    ]
    list_filter = ['category', 'recipient_type', 'is_read']
    search_fields = ['title', 'message']
    readonly_fields = ['id', 'created_at', 'read_at']
    ordering = ['-created_at']
