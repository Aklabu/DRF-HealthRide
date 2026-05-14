from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0003_add_unassigned_status'),
    ]

    operations = [
        # Rename existing 'confirmed' data values to 'scheduled'
        migrations.RunSQL(
            sql="UPDATE trips SET status = 'scheduled' WHERE status = 'confirmed';",
            reverse_sql="UPDATE trips SET status = 'confirmed' WHERE status = 'scheduled';",
        ),
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
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=25,
            ),
        ),
    ]
