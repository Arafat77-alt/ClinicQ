"""Admin site setup for the queueing application."""

from django.contrib import admin

from .models import QueueEntry


@admin.register(QueueEntry)
class QueueEntryAdmin(admin.ModelAdmin):
    """Let staff view queue entries in the Django admin site."""

    list_display = ("token", "doctor", "queue_date", "state", "is_emergency", "skip_count")
    list_filter = ("state", "is_emergency", "doctor", "queue_date")
    search_fields = ("appointment__reference_number", "appointment__patient__full_name")
