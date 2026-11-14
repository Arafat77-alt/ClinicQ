"""Admin site setup for the booking application."""

from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    """Let staff view and create appointments in the Django admin site."""

    list_display = ("reference_number", "patient", "doctor", "slot_start", "type", "status")
    list_filter = ("status", "type", "doctor")
    search_fields = ("reference_number", "patient__full_name", "patient__mobile_number")
    readonly_fields = ("reference_number", "created_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        """Record which account created a new appointment."""
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)