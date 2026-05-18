"""
Migration: add awaiting_signature to Trip.status choices.

The existing chain (0001–0005) already covers:
  pending, unassigned, driver_selected, scheduled,
  on_way, in_progress, completed, cancelled, driver_absence

This migration adds the missing awaiting_signature status used by the
driver_app signature capture flow.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0005_add_driver_absence_status'),
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
                    ('scheduled', 'Scheduled'),
                    ('on_way', 'On Way'),
                    ('in_progress', 'In Progress'),
                    ('awaiting_signature', 'Awaiting Signature'),
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                    ('driver_absence', 'Driver Absence'),
                ],
                default='pending',
                max_length=25,
            ),
        ),
    ]
