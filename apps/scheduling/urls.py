from django.urls import path
from .views import (
    DailyScheduleTodayView,
    DailyScheduleDateView,
    AutoAssignView,
    ScheduleSlotReassignView,
)

urlpatterns = [
    # Today's schedule
    path('daily/', DailyScheduleTodayView.as_view(), name='schedule-today'),

    # Schedule for a specific date
    path('daily/<str:date>/', DailyScheduleDateView.as_view(), name='schedule-date'),

    # AI auto-assignment
    path('auto-assign/', AutoAssignView.as_view(), name='schedule-auto-assign'),

    # Manual slot reassignment
    path('slots/<uuid:id>/', ScheduleSlotReassignView.as_view(), name='schedule-slot-reassign'),
]
