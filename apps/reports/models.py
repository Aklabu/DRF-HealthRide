import uuid
from django.db import models
from apps.accounts.models import Provider


REPORT_TYPE_CHOICES = [
    ('trip_volume', 'Trip Volume'),
    ('driver_hours', 'Driver Hours'),
    ('passenger_service', 'Passenger Service'),
]


class ReportSnapshot(models.Model):
    """
    Cached aggregation results for expensive report queries.
    One record per provider per report type per date range.
    Updated in place on recompute — never duplicated.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name='report_snapshots'
    )
    report_type = models.CharField(max_length=25, choices=REPORT_TYPE_CHOICES)
    date_range_start = models.DateField()
    date_range_end = models.DateField()

    # Serialized aggregation result
    data = models.JSONField(default=dict)

    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'report_snapshots'
        # One snapshot per provider per report type per date range
        unique_together = [('provider', 'report_type', 'date_range_start', 'date_range_end')]

    def __str__(self):
        return (
            f'{self.report_type} snapshot for {self.provider.business_email} '
            f'({self.date_range_start} → {self.date_range_end})'
        )

    def is_valid(self):
        from django.utils import timezone
        return self.expires_at > timezone.now()


class DashboardCache(models.Model):
    """
    Stores the last computed dashboard response per provider.
    One record per provider — upserted on every recompute.
    Short TTL (5 minutes) — near-real-time dashboard data.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # unique=True — one cache record per provider
    provider = models.OneToOneField(
        Provider, on_delete=models.CASCADE, related_name='dashboard_cache'
    )

    # Aggregated header counts (active trips, completed today, revenue today, cancellations)
    header_data = models.JSONField(default=dict)

    # Daily/weekly earnings series for chart rendering
    earnings_chart_data = models.JSONField(default=dict)

    # Driver availability counts
    driver_status_data = models.JSONField(default=dict)

    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'dashboard_cache'

    def __str__(self):
        return f'Dashboard cache for {self.provider.business_email}'

    def is_valid(self):
        from django.utils import timezone
        return self.expires_at > timezone.now()
