"""
Migration: convert DriverLocation.driver from ForeignKey to OneToOneField.

Steps:
1. Delete duplicate rows (keep the most recently updated one per driver).
   Uses a SQLite-compatible subquery instead of DISTINCT ON.
2. Alter the field to OneToOneField (adds unique constraint at DB level).
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracking', '0001_initial'),
        ('drivers', '0002_initial'),
    ]

    operations = [
        # Step 1 — remove duplicate driver rows, keeping the latest timestamp.
        # SQLite-compatible: delete rows whose id is NOT the max-id per driver.
        # (auto_now=True means the most recently written row has the highest
        # rowid / UUID insertion order — using MAX(id) is a safe proxy here,
        # but we use a self-join on timestamp to be precise.)
        migrations.RunSQL(
            sql="""
                DELETE FROM driver_locations
                WHERE id NOT IN (
                    SELECT id FROM driver_locations dl1
                    WHERE dl1.timestamp = (
                        SELECT MAX(dl2.timestamp)
                        FROM driver_locations dl2
                        WHERE dl2.driver_id = dl1.driver_id
                    )
                );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Step 2 — alter ForeignKey → OneToOneField (adds unique constraint)
        migrations.AlterField(
            model_name='driverlocation',
            name='driver',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='location',
                to='drivers.driver',
            ),
        ),
    ]
