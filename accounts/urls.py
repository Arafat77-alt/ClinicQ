"""Web addresses for the accounts application."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.ClinicLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("patient/register/", views.patient_register, name="patient_register"),
    path(
        "patient/register/verify/",
        views.patient_register_verify,
        name="patient_register_verify",
    ),
    path("patient/login/", views.patient_login, name="patient_login"),
    path(
        "patient/login/verify/",
        views.patient_login_verify,
        name="patient_login_verify",
    ),
    path("password/change/", views.FirstPasswordChangeView.as_view(), name="password_change"),
    path("password/reset/", views.ClinicPasswordResetView.as_view(), name="password_reset"),
    path(
        "password/reset/sent/",
        views.ClinicPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password/reset/<uidb64>/<token>/",
        views.ClinicPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        views.ClinicPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/new/", views.staff_create, name="staff_create"),
    path("staff/<int:user_id>/deactivate/", views.staff_deactivate, name="staff_deactivate"),
]