import uuid
from django.db import models
from apps.accounts.models import Provider
from apps.trips.models import Trip
from apps.drivers.models import Driver


# Assignment method choices for ScheduleSlot
ASSIGNMENT_METHOD_CHOICES = [
    ('manual', 'Manual'),
    ('ai', 'AI'),
    ('unassigned', 'Unassigned'),
]


# One record per provider per date — auto-created when first trip is scheduled for that date
class DailySchedule(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='daily_schedules')
    date = models.DateField()

    # Denormalized stats — updated incrementally by trips app on status changes
    total_trips = models.PositiveIntegerField(default=0)
    completed_trips = models.PositiveIntegerField(default=0)
    in_progress = models.PositiveIntegerField(default=0)   # active or in_route
    scheduled = models.PositiveIntegerField(default=0)     # scheduled with driver assigned
    unassigned = models.PositiveIntegerField(default=0)    # scheduled with no driver

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_schedules'
        unique_together = [('provider', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'Schedule {self.date} — {self.provider.business_email}'

    def refresh_stats(self):
        """Recompute all header stats from ScheduleSlot + Trip data."""
        slots = self.slots.select_related('trip', 'driver')
        total = slots.count()
        completed = slots.filter(trip__status='completed').count()
        in_progress = slots.filter(trip__status__in=['active', 'in_route']).count()
        scheduled = slots.filter(
            trip__status='scheduled', driver__isnull=False
        ).count()
        unassigned = slots.filter(
            trip__status='scheduled', driver__isnull=True
        ).count()

        self.total_trips = total
        self.completed_trips = completed
        self.in_progress = in_progress
        self.scheduled = scheduled
        self.unassigned = unassigned
        self.save(update_fields=[
            'total_trips', 'completed_trips', 'in_progress', 'scheduled', 'unassigned'
        ])


# One slot per trip per daily schedule — source of truth for daily assignment state
class ScheduleSlot(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.ForeignKey(DailySchedule, on_delete=models.CASCADE, related_name='slots')
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='schedule_slots')
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='schedule_slots'
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    assignment_method = models.CharField(
        max_length=20, choices=ASSIGNMENT_METHOD_CHOICES, default='unassigned'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'schedule_slots'
        unique_together = [('schedule', 'trip')]
        ordering = ['trip__pickup_time']

    def __str__(self):
        return f'Slot {self.trip.trip_number} on {self.schedule.date}'


# Full audit log of every AI assignment attempt — stores all candidates scored
class AIAssignmentLog(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='ai_assignment_logs')
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='ai_assignment_logs')

    # Full scored candidate list — array of { driver_id, driver_name, distance_miles,
    # current_load, availability_match, vehicle_match, score }
    drivers_considered = models.JSONField(default=list)

    selected_driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ai_assignment_selections'
    )
    assignment_successful = models.BooleanField(default=False)

    # Human-readable explanation of selection or failure reason
    reason = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_assignment_logs'
        ordering = ['-created_at']

    def __str__(self):
        status = 'success' if self.assignment_successful else 'failed'
        return f'AI assignment for {self.trip.trip_number} — {status}'
