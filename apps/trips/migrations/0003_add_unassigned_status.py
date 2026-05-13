"""
Migration: Add 'unassigned' status to Trip model.

Changes:
- Add 'unassigned' status to TRIP_STATUS_CHOICES
- Trips are marked as unassigned when no drivers are available at pickup time
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0002_redesign_trip_booking_flow'),
    ]

    operations = [
        migrations.AlterField(
            model_name='trip',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('unassigned', 'Unassigned'),
                    ('driver_selected', 'Driver Selected'),
                    ('confirmed', 'Confirmed'),
                    ('on_way', 'On Way'),
                    ('in_progress', 'In Progress'),
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=25,
            ),
        ),
    ]
