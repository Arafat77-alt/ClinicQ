"""Tests for NOT-01 booking confirmation messages."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Patient, User
from booking.models import Appointment
from notifications.models import Notification
from notifications.services import (
    send_booking_confirmation,
    send_cancellation_confirmation,
    send_reschedule_confirmation,
)
from scheduling.models import Doctor


class BookingConfirmationTests(TestCase):
    """NOT-01, REL-04, PRIV-01 and USAB-06 confirmation behaviour."""

    def setUp(self):
        """Create one booked appointment with a known Dhaka time."""
        doctor_user = User.objects.create_user(
            username="dr_imran",
            password="test-pass-123",
            first_name="Imran",
            last_name="Hossain",
            role=User.Role.DOCTOR,
        )
        self.doctor = Doctor.objects.create(
            user=doctor_user,
            code="D1",
            specialty="Cardiology",
            room="101",
        )
        patient_user = User.objects.create_user(
            username="rahima",
            password="test-pass-123",
            email="rahima@example.com",
            role=User.Role.PATIENT,
        )
        self.patient = Patient.objects.create(
            user=patient_user,
            full_name="Rahima Akter",
            mobile_number="+8801712345678",
        )
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            slot_start=datetime(2026, 11, 24, 11, 0, tzinfo=UTC),
            slot_end=datetime(2026, 11, 24, 11, 30, tzinfo=UTC),
            type=Appointment.Type.RECEPTION,
            status=Appointment.Status.BOOKED,
            reason="Severe chest pain",
        )

    def test_booking_confirmation_has_only_needed_details_in_dhaka_time(self):
        """USAB-06 and PRIV-01: short, clear, and free of medical details."""
        with patch("notifications.services.send_sms", return_value=True) as sms:
            notification = send_booking_confirmation(self.appointment)

        sms.assert_called_once()
        self.assertEqual(notification.event, Notification.Event.BOOKED)
        self.assertEqual(notification.channel, Notification.Channel.SMS)
        self.assertEqual(notification.status, Notification.Status.SENT)
        self.assertEqual(notification.attempts, 1)
        self.assertIsNotNone(notification.sent_at)
        self.assertIn("Dr. Imran Hossain (D1)", notification.message)
        self.assertIn("24 Nov 2026 at 17:00", notification.message)
        self.assertIn(self.appointment.reference_number, notification.message)
        self.assertNotIn("Severe chest pain", notification.message)

    def test_confirmation_is_available_within_one_minute(self):
        """The message is stored and sent immediately after the booking."""
        with patch("notifications.services.send_sms", return_value=True):
            notification = send_booking_confirmation(self.appointment)

        self.assertLessEqual(timezone.now() - notification.created_at, timedelta(minutes=1))
        self.assertLessEqual(timezone.now() - notification.sent_at, timedelta(minutes=1))

    def test_email_is_used_when_there_is_no_mobile_number(self):
        """SMS or email is enough; either channel confirms the appointment."""
        self.patient.mobile_number = ""
        self.patient.save(update_fields=["mobile_number"])

        with (
            patch("notifications.services.send_sms") as sms,
            patch("notifications.services.send_email", return_value=True) as email,
        ):
            notification = send_booking_confirmation(self.appointment)

        sms.assert_not_called()
        email.assert_called_once()
        self.assertEqual(notification.channel, Notification.Channel.EMAIL)
        self.assertEqual(notification.status, Notification.Status.SENT)
        self.assertEqual(notification.recipient, "rahima@example.com")

    def test_failed_sms_retries_three_times_and_keeps_in_app_message(self):
        """REL-04: failures never undo the booking and the text is kept."""
        self.patient.user = None
        self.patient.save(update_fields=["user"])

        with (
            patch("notifications.services.send_sms", side_effect=RuntimeError("sms down")) as sms,
            patch("notifications.services.send_email") as email,
        ):
            notification = send_booking_confirmation(self.appointment)

        self.assertEqual(sms.call_count, 3)
        email.assert_not_called()
        self.assertEqual(notification.channel, Notification.Channel.IN_APP)
        self.assertEqual(notification.status, Notification.Status.IN_APP)
        self.assertEqual(notification.attempts, 3)
        self.assertIsNone(notification.sent_at)
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())

    def test_confirmation_never_raises_when_storage_fails(self):
        """REL-04: a notification failure must not break the caller."""
        with (
            patch(
                "notifications.services.Notification.objects.create",
                side_effect=RuntimeError("database down"),
            ),
            patch("notifications.services.logger.exception") as log_error,
        ):
            result = send_booking_confirmation(self.appointment)

        log_error.assert_called_once()

        self.assertIsNone(result)

    def test_cancellation_and_reschedule_messages_are_plain_language(self):
        """The same safe helper covers cancellations and reschedules."""
        with patch("notifications.services.send_sms", return_value=True):
            cancelled = send_cancellation_confirmation(self.appointment)
            rescheduled = send_reschedule_confirmation(self.appointment)

        self.assertEqual(cancelled.event, Notification.Event.CANCELLED)
        self.assertIn("is cancelled", cancelled.message)
        self.assertEqual(rescheduled.event, Notification.Event.RESCHEDULED)
        self.assertIn("has moved to", rescheduled.message)
        self.assertNotIn("Severe chest pain", cancelled.message)
        self.assertNotIn("Severe chest pain", rescheduled.message)
