"""
Celery configuration for HealthRide NEMT.

Workers are started with:
    celery -A config worker -l info

Beat scheduler (for periodic tasks like apply_late_fees, scan_document_expiry):
    celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('healthride')

# Read config from Django settings, namespace CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
