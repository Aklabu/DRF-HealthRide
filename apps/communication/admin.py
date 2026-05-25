from django.contrib import admin
from .models import Conversation, Message, BroadcastMessage


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['provider', 'driver', 'last_message_at', 'created_at']
    search_fields = ['provider__business_email', 'driver__full_name']
    readonly_fields = ['id', 'created_at']
    ordering = ['-last_message_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'sender_type', 'content', 'is_read', 'sent_at']
    list_filter = ['sender_type', 'is_read']
    search_fields = ['content', 'conversation__driver__full_name']
    readonly_fields = ['id', 'sent_at', 'read_at']
    ordering = ['-sent_at']


@admin.register(BroadcastMessage)
class BroadcastMessageAdmin(admin.ModelAdmin):
    list_display = ['provider', 'content', 'recipient_count', 'sent_at']
    search_fields = ['provider__business_email', 'content']
    readonly_fields = ['id', 'sent_at']
    ordering = ['-sent_at']
