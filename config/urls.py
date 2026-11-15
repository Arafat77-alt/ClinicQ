"""URL configuration for ClinicQ."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("schedule/", include("scheduling.urls")),
    path("", include("accounts.urls")),
]