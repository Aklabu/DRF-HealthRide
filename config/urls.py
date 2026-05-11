"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include('apps.accounts.urls')),
    path('api/vehicles/', include('apps.vehicles.urls')),
    path('api/drivers/', include('apps.drivers.urls')),
    path('api/passengers/', include('apps.passengers.urls')),
    path('api/facilities/', include('apps.facilities.urls')),
    path('api/trips/', include('apps.trips.urls')),
    path('api/scheduling/', include('apps.scheduling.urls')),
    path('api/tracking/', include('apps.tracking.urls')),
    path('api/billing/', include('apps.billing.urls')),
    path('api/compliance/', include('apps.compliance.urls')),
    path('api/', include('apps.reports.urls')),
    path('api/notifications/', include('apps.notifications.urls')),
    path('api/communication/', include('apps.communication.urls')),
    path('api/driver/', include('apps.driver_app.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)