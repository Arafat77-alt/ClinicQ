"""Web addresses for the consultation application (VIS-01)."""

from django.urls import path

from . import views

app_name = "consultation"

urlpatterns = [
    path("queue-entry/<int:entry_id>/notes/", views.visit_notes, name="visit_notes"),
    path("records/<int:record_id>/", views.visit_record_detail, name="visit_record_detail"),
]
