"""
Migration: align Trip.status choices to the canonical set.

Replaces the old in_route/active values with on_way/in_progress in both
the choices list and any existing rows.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0001_initial'),
    ]

    operations = [
        # Step 1 — migrate any existing rows that used the old status values
        migrations.RunSQL(
            sql="""
                UPDATE trips SET status = 'on_way'      WHERE status = 'in_route';
                UPDATE trips SET status = 'in_progress' WHERE status = 'active';
            """,
            reverse_sql="""
                UPDATE trips SET status = 'in_route' WHERE status = 'on_way';
                UPDATE trips SET status = 'active'   WHERE status = 'in_progress';
            """,
        ),

        # Step 2 — update the choices on the model field
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
