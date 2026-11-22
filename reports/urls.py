"""Web addresses for the reports application (SYS-04)."""

from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("schedule/print/", views.print_schedule, name="print_schedule"),
]
