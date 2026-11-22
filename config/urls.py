"""URL configuration for ClinicQ."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("booking/", include("booking.urls")),
    path("consultation/", include("consultation.urls")),
    path("queue/", include("queueing.urls")),
    path("queue/reception/", include("queueing.reception_urls")),
    path("reports/", include("reports.urls")),
    path("schedule/", include("scheduling.urls")),
    path("", include("accounts.urls")),
]
