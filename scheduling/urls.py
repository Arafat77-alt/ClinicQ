"""Web addresses for the scheduling application."""

from django.urls import path

from . import views

app_name = "scheduling"

urlpatterns = [
    path("availability/", views.availability, name="availability"),
    path("availability/new/", views.rule_add, name="rule_add"),
    path("availability/<int:rule_id>/delete/", views.rule_delete, name="rule_delete"),
    path("availability/<int:rule_id>/break/new/", views.break_add, name="break_add"),
    path("availability/breaks/<int:break_id>/delete/", views.break_delete, name="break_delete"),
]