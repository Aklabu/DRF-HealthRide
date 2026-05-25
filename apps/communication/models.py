import uuid
from django.db import models
from apps.accounts.models import Provider
from apps.drivers.models import Driver


SENDER_TYPE_CHOICES = [
    ('provider', 'Provider'),
    ('driver', 'Driver'),
]


class Conversation(models.Model):
    """
    One thread per provider-driver pair — never duplicated.
    unique_together(provider, driver) enforces this at DB level.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='conversations'
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name='conversations'
    )

    # Updated on every new message — drives ordering in conversation list
    last_message_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'conversations'
        unique_together = [('provider', 'driver')]
        ordering = ['-last_message_at']

    def __str__(self):
        return f'Conversation: {self.provider.business_email} ↔ {self.driver.full_name}'


class Message(models.Model):
    """
    Individual message within a conversation.
    Persisted regardless of whether WS or HTTP path was used.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages'
    )
    sender_type = models.CharField(max_length=10, choices=SENDER_TYPE_CHOICES)
    sender_id = models.UUIDField()
    content = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messages'
        ordering = ['sent_at']
        indexes = [
            models.Index(fields=['conversation', 'is_read', 'sender_type']),
        ]

    def __str__(self):
        return f'[{self.sender_type}] {self.content[:50]}'


class BroadcastMessage(models.Model):
    """
    Provider-to-all-drivers broadcast.
    Created immediately — per-driver notifications dispatched async via Celery.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='broadcasts'
    )
    content = models.TextField()
    recipient_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'broadcast_messages'
        ordering = ['-sent_at']

    def __str__(self):
        return f'Broadcast by {self.provider.business_email} to {self.recipient_count} drivers'
