"""Web addresses for the scheduling application."""

from django.urls import path

from . import profile_views, views

app_name = "scheduling"

urlpatterns = [
    path("availability/", views.availability, name="availability"),
    path("availability/new/", views.rule_add, name="rule_add"),
    path("availability/<int:rule_id>/delete/", views.rule_delete, name="rule_delete"),
    path("availability/<int:rule_id>/break/new/", views.break_add, name="break_add"),
    path("availability/breaks/<int:break_id>/delete/", views.break_delete, name="break_delete"),
    path("leave/", views.leave_list, name="leave_list"),
    path("leave/<int:leave_id>/delete/", views.leave_delete, name="leave_delete"),
    path("doctors/", profile_views.doctor_list, name="doctor_list"),
    path("doctors/new/", profile_views.doctor_create, name="doctor_create"),
    path("doctors/<int:doctor_id>/edit/", profile_views.doctor_edit, name="doctor_edit"),
    path("doctors/<int:doctor_id>/delete/", profile_views.doctor_delete, name="doctor_delete"),
    path(
        "doctors/<int:doctor_id>/deactivate/",
        profile_views.doctor_deactivate,
        name="doctor_deactivate",
    ),
]
