from django.contrib import admin
from .models import ReportSnapshot, DashboardCache


@admin.register(ReportSnapshot)
class ReportSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        'report_type', 'provider', 'date_range_start', 'date_range_end',
        'generated_at', 'expires_at',
    ]
    list_filter = ['report_type']
    search_fields = ['provider__business_email']
    readonly_fields = ['id', 'generated_at', 'expires_at']
    ordering = ['-generated_at']


@admin.register(DashboardCache)
class DashboardCacheAdmin(admin.ModelAdmin):
    list_display = ['provider', 'generated_at', 'expires_at']
    readonly_fields = ['id', 'generated_at', 'expires_at']
    search_fields = ['provider__business_email']
