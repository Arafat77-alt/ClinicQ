"""Web addresses for the queueing application."""

from django.urls import path

from . import live_views

app_name = "queueing"

urlpatterns = [
    path("live/<int:appointment_id>/", live_views.live_status, name="live_status"),
    path("live/<int:appointment_id>/data/", live_views.live_status_json, name="live_status_json"),
]
