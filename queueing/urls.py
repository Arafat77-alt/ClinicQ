"""Web addresses for the queueing application."""

from django.urls import path

from . import doctor_views, live_views

app_name = "queueing"

urlpatterns = [
    path("doctor/live/", doctor_views.live_queue, name="doctor_live_queue"),
    path("doctor/live/data/", doctor_views.live_queue_data, name="doctor_live_queue_data"),
    path("live/<int:appointment_id>/", live_views.live_status, name="live_status"),
    path("live/<int:appointment_id>/data/", live_views.live_status_json, name="live_status_json"),
]
