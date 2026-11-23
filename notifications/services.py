"""Appointment and leave notification messages for patients.

NOT-01 confirms booking changes. NOT-03 tells patients when leave affects
an appointment. REL-04 keeps the main action safe: failures never reach callers.
"""

import logging
import os
from zoneinfo import ZoneInfo

from django.urls import reverse
from django.utils import timezone

from .models import Notification

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 3
DHAKA_TIME_ZONE = ZoneInfo("Asia/Dhaka")
DEFAULT_CLINICQ_BASE_URL = "http://127.0.0.1:8000"
LEAVE_NOTICE_SUBJECT = "Appointment needs a new time"

EVENT_TEMPLATES = {
    Notification.Event.BOOKED: (
        "Your appointment is confirmed with {doctor} on {when}. Reference {reference}."
    ),
    Notification.Event.CANCELLED: (
        "Your appointment with {doctor} on {when} is cancelled. Reference {reference}."
    ),
    Notification.Event.RESCHEDULED: (
        "Your appointment with {doctor} has moved to {when}. Reference {reference}."
    ),
}

EVENT_SUBJECTS = {
    Notification.Event.BOOKED: "Appointment confirmed",
    Notification.Event.CANCELLED: "Appointment cancelled",
    Notification.Event.RESCHEDULED: "Appointment rescheduled",
}


def _appointment_when(appointment):
    """Return the appointment time in Dhaka using plain language."""
    if appointment.slot_start is None:
        return "a time to be confirmed at the clinic"
    local_start = timezone.localtime(appointment.slot_start, DHAKA_TIME_ZONE)
    return f"{local_start:%d %b %Y} at {local_start:%H:%M}"


def _doctor_label(appointment):
    """Return only the doctor name and code needed to identify the visit."""
    doctor = appointment.doctor
    user = doctor.user
    name = user.get_full_name() or user.username
    return f"Dr. {name} ({doctor.code})"


def _confirmation_message(appointment, event):
    """Build a short message with no medical details."""
    return EVENT_TEMPLATES[event].format(
        doctor=_doctor_label(appointment),
        when=_appointment_when(appointment),
        reference=appointment.reference_number,
    )


def _appointment_link(appointment):
    """Return the patient appointment page as an absolute link."""
    base_url = os.getenv("CLINICQ_BASE_URL", DEFAULT_CLINICQ_BASE_URL).rstrip("/")
    return f"{base_url}{reverse('booking:my_appointments')}"


def _leave_notice_message(appointment):
    """Build a leave message with the original time, reference, and link."""
    return (
        f"{_doctor_label(appointment)} is on leave. "
        f"Your appointment on {_appointment_when(appointment)}, "
        f"reference {appointment.reference_number}, needs a new time. "
        f"Open {_appointment_link(appointment)} to cancel it or book a new slot."
    )


def _patient_mobile(appointment):
    """Return the patient's saved mobile number, if there is one."""
    return (getattr(appointment.patient, "mobile_number", "") or "").strip()


def _patient_email(appointment):
    """Return the patient's email address, if their account has one."""
    user = getattr(appointment.patient, "user", None)
    return (getattr(user, "email", "") or "").strip()


def _deliver(appointment, notification, message, subject=None):
    """Try SMS, then email, using at most three attempts in total."""
    attempts = 0
    mobile = _patient_mobile(appointment)
    if mobile:
        for _ in range(MAX_DELIVERY_ATTEMPTS):
            attempts += 1
            try:
                if send_sms(mobile, message):
                    return Notification.Channel.SMS, Notification.Status.SENT, attempts, mobile
            except Exception:
                logger.debug("SMS confirmation failed on attempt %s", attempts, exc_info=True)

    email = _patient_email(appointment)
    if email:
        while attempts < MAX_DELIVERY_ATTEMPTS:
            attempts += 1
            try:
                email_subject = subject or EVENT_SUBJECTS[notification.event]
                if send_email(email, email_subject, message):
                    return Notification.Channel.EMAIL, Notification.Status.SENT, attempts, email
            except Exception:
                logger.debug("Email confirmation failed on attempt %s", attempts, exc_info=True)

    return Notification.Channel.IN_APP, Notification.Status.IN_APP, attempts, ""


def _record_and_deliver(appointment, event, subject, message):
    """Store and send one notification without raising into the caller."""
    appointment_id = getattr(appointment, "pk", None)
    try:
        notification = Notification.objects.create(
            event=event,
            appointment=appointment,
            patient=appointment.patient,
            subject=subject,
            message=message,
            recipient=_patient_mobile(appointment) or _patient_email(appointment),
        )
        channel, status, attempts, recipient = _deliver(
            appointment, notification, message, subject=subject
        )
        notification.channel = channel
        notification.status = status
        notification.attempts = attempts
        notification.recipient = recipient or notification.recipient
        notification.sent_at = timezone.now() if status == Notification.Status.SENT else None
        notification.save(
            update_fields=["channel", "status", "attempts", "recipient", "sent_at", "updated_at"]
        )
        return notification
    except Exception:
        logger.exception("Could not store or send notice for appointment %s", appointment_id)
        return None


def send_appointment_confirmation(appointment, event=Notification.Event.BOOKED):
    """Store and send a confirmation without raising into the booking flow."""
    appointment_id = getattr(appointment, "pk", None)
    try:
        if event not in EVENT_TEMPLATES:
            logger.warning("Unsupported confirmation event %s", event)
            return None
        return _record_and_deliver(
            appointment,
            event,
            EVENT_SUBJECTS[event],
            _confirmation_message(appointment, event),
        )
    except Exception:
        logger.exception("Could not store or send confirmation for appointment %s", appointment_id)
        return None


def send_booking_confirmation(appointment):
    """Confirm that a new appointment was saved."""
    return send_appointment_confirmation(appointment, Notification.Event.BOOKED)


def send_cancellation_confirmation(appointment):
    """Confirm that an appointment was cancelled."""
    return send_appointment_confirmation(appointment, Notification.Event.CANCELLED)


def send_reschedule_confirmation(appointment):
    """Confirm that an appointment moved to a new time."""
    return send_appointment_confirmation(appointment, Notification.Event.RESCHEDULED)


def send_leave_notice(appointment):
    """Tell a patient that leave affects their appointment without raising."""
    try:
        notification = _record_and_deliver(
            appointment,
            Notification.Event.RESCHEDULED,
            LEAVE_NOTICE_SUBJECT,
            _leave_notice_message(appointment),
        )
        return notification is not None and notification.status == Notification.Status.SENT
    except Exception:
        appointment_id = getattr(appointment, "pk", None)
        logger.exception("Could not send leave notice for appointment %s", appointment_id)
        return False


def send_sms(recipient, message):
    """Print a text message to the terminal instead of sending it.

    Args:
        recipient (str): Mobile number, for example +8801712345678.
        message (str): The text of the message.

    Returns:
        bool: True when the message was handled.

    Raises:
        ValueError: If no mobile number was given.
    """
    if not recipient or not recipient.strip():
        raise ValueError(
            "No mobile number was given. Please enter a mobile number "
            "such as +8801712345678 and try again."
        )
    print(f"[SMS] To: {recipient} | Message: {message}")
    return True


def send_email(recipient, subject, message):
    """Print an email to the terminal instead of sending it.

    Args:
        recipient (str): Email address of the receiver.
        subject (str): The subject line.
        message (str): The body of the email.

    Returns:
        bool: True when the email was handled.

    Raises:
        ValueError: If no email address was given.
    """
    if not recipient or not recipient.strip():
        raise ValueError(
            "No email address was given. Please enter an email address "
            "such as name@example.com and try again."
        )
    print(f"[EMAIL] To: {recipient} | Subject: {subject} | Message: {message}")
    return True
