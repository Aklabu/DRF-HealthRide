import uuid
from django.db import models
from apps.accounts.models import Provider


RECIPIENT_TYPE_CHOICES = [
    ('provider', 'Provider'),
    ('driver', 'Driver'),
]

CATEGORY_CHOICES = [
    ('trip', 'Trip'),
    ('driver', 'Driver'),
    ('payment', 'Payment'),
    ('announcement', 'Announcement'),
    ('compliance', 'Compliance'),
]


class NotificationPreference(models.Model):
    """
    Per-recipient notification preferences.
    Auto-created on provider account creation and driver creation.
    unique_together(recipient_type, recipient_id) — one record per recipient.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient_type = models.CharField(max_length=10, choices=RECIPIENT_TYPE_CHOICES)
    recipient_id = models.UUIDField()
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='notification_preferences'
    )

    # Category toggles
    trip_updates = models.BooleanField(default=True)
    driver_alerts = models.BooleanField(default=True)
    passenger_messages = models.BooleanField(default=True)
    financial_alerts = models.BooleanField(default=True)
    announcements = models.BooleanField(default=True)

    # Channel toggles — SMS off by default (per-message cost)
    push_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_preferences'
        unique_together = [('recipient_type', 'recipient_id')]

    def __str__(self):
        return f'Preferences for {self.recipient_type}:{self.recipient_id}'

    def is_category_enabled(self, category):
        """Check if a notification category is enabled for this recipient."""
        category_map = {
            'trip': self.trip_updates,
            'driver': self.driver_alerts,
            'payment': self.financial_alerts,
            'announcement': self.announcements,
            'compliance': self.driver_alerts,  # compliance maps to driver_alerts channel
        }
        return category_map.get(category, True)


class NotificationTemplate(models.Model):
    """
    Provider-defined notification templates with placeholder support.
    Placeholders validated at creation time — not at send time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='notification_templates'
    )
    template_name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    subject = models.CharField(max_length=255)
    content = models.TextField()

    # Soft delete — is_active = False instead of hard delete
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_templates'

    def __str__(self):
        return f'{self.template_name} ({self.category})'


class Notification(models.Model):
    """
    Persistent notification inbox record.
    Only created if the recipient has the category enabled in their preferences.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='notifications'
    )

    recipient_type = models.CharField(max_length=10, choices=RECIPIENT_TYPE_CHOICES)
    recipient_id = models.UUIDField()

    title = models.CharField(max_length=255)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)

    # Deep-link support — clients navigate to related resource on tap
    related_object_type = models.CharField(max_length=50, null=True, blank=True)
    related_object_id = models.UUIDField(null=True, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient_type', 'recipient_id', 'is_read']),
        ]

    def __str__(self):
        return f'[{self.category}] {self.title} → {self.recipient_type}:{self.recipient_id}'
