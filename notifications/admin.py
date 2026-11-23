"""Admin registration for notifications."""

from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Show stored confirmation messages in the admin."""

    list_display = ("event", "patient", "channel", "status", "attempts", "created_at")
    list_filter = ("event", "channel", "status")
    search_fields = (
        "patient__full_name",
        "recipient",
        "message",
        "appointment__reference_number",
    )
