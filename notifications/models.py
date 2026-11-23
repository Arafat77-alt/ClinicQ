"""Persistent records for patient notifications."""

from django.db import models


class Notification(models.Model):
    """A message kept for a patient and, when possible, sent by SMS or email."""

    class Event(models.TextChoices):
        """The appointment change the patient is told about."""

        BOOKED = "booked", "Booked"
        CANCELLED = "cancelled", "Cancelled"
        RESCHEDULED = "rescheduled", "Rescheduled"

    class Channel(models.TextChoices):
        """How the message was delivered, or kept for the in-app inbox."""

        SMS = "sms", "SMS"
        EMAIL = "email", "Email"
        IN_APP = "in_app", "In-app"

    class Status(models.TextChoices):
        """The result of the delivery attempt."""

        SENT = "sent", "Sent"
        IN_APP = "in_app", "In-app"

    event = models.CharField(max_length=16, choices=Event.choices)
    appointment = models.ForeignKey(
        "booking.Appointment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    patient = models.ForeignKey(
        "accounts.Patient",
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    subject = models.CharField(max_length=100)
    message = models.TextField()
    recipient = models.CharField(max_length=150, blank=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.IN_APP)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.IN_APP)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Show newest messages first."""

        ordering = ["-created_at"]

    def __str__(self):
        """Return short, non-medical details for staff lists."""
        return f"{self.get_event_display()}: {self.appointment_id} ({self.status})"
