"""
Migration: Redesign trip booking flow to 3-step process.

Changes to Trip model:
- Remove: mileage_cost, total_amount (old pricing fields)
- Remove: old status choices (scheduled, in_route, active, awaiting_signature)
- Remove: old payment_method choices (pay_later)
- Add: new pricing fields (mileage_rate, total_mileage_cost, subtotal, trip_multiplier, estimated_total)
- Add: coordinate fields (pickup_latitude, pickup_longitude, dropoff_latitude, dropoff_longitude)
- Add: authorization_number, medical_notes
- Add: payment_delivery, payment_link
- Add: confirmed_at timestamp
- Update: status choices to new 3-step lifecycle
- Update: payment_method choices to include send_link, payment_later
- Update: payment_status choices to include pending
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0001_initial'),
    ]

    operations = [
        # ── Remove old pricing fields ──────────────────────────────────────
        migrations.RemoveField(model_name='trip', name='mileage_cost'),
        migrations.RemoveField(model_name='trip', name='total_amount'),

        # ── Add new pricing fields ─────────────────────────────────────────
        migrations.AddField(
            model_name='trip',
            name='mileage_rate',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=8),
        ),
        migrations.AddField(
            model_name='trip',
            name='total_mileage_cost',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=8),
        ),
        migrations.AddField(
            model_name='trip',
            name='subtotal',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=10),
        ),
        migrations.AddField(
            model_name='trip',
            name='trip_multiplier',
            field=models.DecimalField(decimal_places=2, default=1.0, max_digits=4),
        ),
        migrations.AddField(
            model_name='trip',
            name='estimated_total',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=10),
        ),

        # ── Add coordinate fields ──────────────────────────────────────────
        migrations.AddField(
            model_name='trip',
            name='pickup_latitude',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='trip',
            name='pickup_longitude',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='trip',
            name='dropoff_latitude',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='trip',
            name='dropoff_longitude',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),

        # ── Add authorization & medical fields ─────────────────────────────
        migrations.AddField(
            model_name='trip',
            name='authorization_number',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='trip',
            name='medical_notes',
            field=models.TextField(blank=True, null=True),
        ),

        # ── Add payment delivery & link fields ─────────────────────────────
        migrations.AddField(
            model_name='trip',
            name='payment_delivery',
            field=models.CharField(
                blank=True, null=True,
                choices=[('sms', 'SMS'), ('email', 'Email')],
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='trip',
            name='payment_link',
            field=models.URLField(blank=True, null=True),
        ),

        # ── Add confirmed_at timestamp ─────────────────────────────────────
        migrations.AddField(
            model_name='trip',
            name='confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),

        # ── Update status choices to new 3-step lifecycle ──────────────────
        migrations.AlterField(
            model_name='trip',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
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

        # ── Update payment_method choices ──────────────────────────────────
        migrations.AlterField(
            model_name='trip',
            name='payment_method',
            field=models.CharField(
                blank=True, null=True,
                choices=[
                    ('cash', 'Cash'),
                    ('card', 'Card'),
                    ('insurance', 'Insurance'),
                    ('send_link', 'Send Link'),
                    ('payment_later', 'Payment Later'),
                ],
                max_length=20,
            ),
        ),

        # ── Update payment_status choices ──────────────────────────────────
        migrations.AlterField(
            model_name='trip',
            name='payment_status',
            field=models.CharField(
                choices=[
                    ('paid', 'Paid'),
                    ('unpaid', 'Unpaid'),
                    ('pending', 'Pending'),
                    ('payment_later', 'Payment Later'),
                ],
                default='unpaid',
                max_length=20,
            ),
        ),
    ]
