"""Admin site setup for the accounts application."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class ClinicUserAdmin(UserAdmin):
    """Show the role field in the Django admin site."""

    fieldsets = UserAdmin.fieldsets + (("Clinic role", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_active")