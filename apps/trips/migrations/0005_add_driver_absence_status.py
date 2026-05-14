from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0004_rename_confirmed_to_scheduled'),
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
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                    ('driver_absence', 'Driver Absence'),
                ],
                default='pending',
                max_length=25,
            ),
        ),
    ]
