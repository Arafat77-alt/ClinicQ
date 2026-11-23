"""Tests for NOT-03 leave notices."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Patient, User
from booking.models import Appointment
from notifications.models import Notification
from notifications.services import send_leave_notice
from scheduling.models import Doctor


class LeaveNoticeTests(TestCase):
    """NOT-03, REL-04, PRIV-01 and USAB-06 leave notice behaviour."""

    def setUp(self):
        """Create an appointment affected by doctor leave."""
        doctor_user = User.objects.create_user(
            username="dr_imran",
            password="test-pass-123",
            first_name="Imran",
            last_name="Hossain",
            role=User.Role.DOCTOR,
        )
        doctor = Doctor.objects.create(
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
        patient = Patient.objects.create(
            user=patient_user,
            full_name="Rahima Akter",
            mobile_number="+8801712345678",
        )
        self.appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            slot_start=datetime(2026, 11, 24, 11, 0, tzinfo=UTC),
            slot_end=datetime(2026, 11, 24, 11, 30, tzinfo=UTC),
            type=Appointment.Type.RECEPTION,
            status=Appointment.Status.NEEDS_RESCHEDULING,
            reason="Severe chest pain",
        )

    def test_message_has_details_and_default_appointment_link(self):
        """USAB-06 and PRIV-01: clear details, default link, no medical details."""
        with patch.dict(os.environ):
            os.environ.pop("CLINICQ_BASE_URL", None)
            with patch("notifications.services.send_sms", return_value=True) as sms:
                result = send_leave_notice(self.appointment)

        self.assertTrue(result)
        sms.assert_called_once()
        notification = Notification.objects.get()
        self.assertEqual(notification.event, Notification.Event.RESCHEDULED)
        self.assertEqual(notification.subject, "Appointment needs a new time")
        self.assertEqual(notification.status, Notification.Status.SENT)
        self.assertIn("Dr. Imran Hossain (D1)", notification.message)
        self.assertIn("24 Nov 2026 at 17:00", notification.message)
        self.assertIn(self.appointment.reference_number, notification.message)
        self.assertIn("http://127.0.0.1:8000/booking/appointments/mine/", notification.message)
        self.assertNotIn("Severe chest pain", notification.message)
        self.assertLessEqual(timezone.now() - notification.created_at, timedelta(minutes=1))

    def test_configured_base_url_is_used(self):
        """The appointment link honours CLINICQ_BASE_URL when it is set."""
        with (
            patch.dict(os.environ, {"CLINICQ_BASE_URL": "https://clinic.example/"}),
            patch("notifications.services.send_sms", return_value=True),
        ):
            result = send_leave_notice(self.appointment)

        self.assertTrue(result)
        notification = Notification.objects.get()
        self.assertIn("https://clinic.example/booking/appointments/mine/", notification.message)

    def test_email_is_used_when_mobile_number_is_missing(self):
        """SMS or email is enough to notify the patient promptly."""
        patient = self.appointment.patient
        patient.mobile_number = ""
        patient.save(update_fields=["mobile_number"])

        with (
            patch("notifications.services.send_sms") as sms,
            patch("notifications.services.send_email", return_value=True) as email,
        ):
            result = send_leave_notice(self.appointment)

        self.assertTrue(result)
        sms.assert_not_called()
        email.assert_called_once()
        notification = Notification.objects.get()
        self.assertEqual(notification.channel, Notification.Channel.EMAIL)
        self.assertEqual(notification.status, Notification.Status.SENT)

    def test_failed_sms_retries_three_times_and_keeps_in_app_record(self):
        """REL-04: failures never break the leave and the message is kept."""
        patient = self.appointment.patient
        patient.user = None
        patient.save(update_fields=["user"])

        with (
            patch("notifications.services.send_sms", side_effect=RuntimeError("sms down")) as sms,
            patch("notifications.services.send_email") as email,
        ):
            result = send_leave_notice(self.appointment)

        self.assertFalse(result)
        self.assertEqual(sms.call_count, 3)
        email.assert_not_called()
        notification = Notification.objects.get()
        self.assertEqual(notification.channel, Notification.Channel.IN_APP)
        self.assertEqual(notification.status, Notification.Status.IN_APP)
        self.assertEqual(notification.attempts, 3)
        self.assertIsNone(notification.sent_at)

    def test_leave_notice_never_raises_when_storage_fails(self):
        """REL-04: notification storage failure must not reach the caller."""
        with (
            patch(
                "notifications.services.Notification.objects.create",
                side_effect=RuntimeError("database down"),
            ),
            patch("notifications.services.logger.exception") as log_error,
        ):
            result = send_leave_notice(self.appointment)

        self.assertFalse(result)
        log_error.assert_called_once()
        self.assertFalse(Notification.objects.exists())
