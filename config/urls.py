"""URL configuration for ClinicQ."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("booking/", include("booking.urls")),
    path("queue/", include("queueing.urls")),
    path("schedule/", include("scheduling.urls")),
    path("", include("accounts.urls")),
]
