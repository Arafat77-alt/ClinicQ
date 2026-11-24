"""Automated tests for patient OTP registration, login, and session timeout.

Stories: AUTH-01 (patient registration), AUTH-02 (patient OTP login).
Requirements: SEC-04 (5-min expiry, 3 attempts, 15-min block),
SEC-05 (30-min patient session timeout), MAIN-02 (unit tests per rule).
"""

import time
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .middleware import LAST_ACTIVITY_SESSION_KEY
from .models import OtpChallenge, Patient, User
from .services.patient_auth import (
    complete_registration_with_otp,
    request_login_otp,
    request_registration_otp,
    verify_login_otp,
)


class PatientOtpRegistrationTests(TestCase):
    """Tests for AUTH-01 patient self-registration with an OTP."""

    def test_valid_otp_within_5_minutes_creates_patient_and_user(self):
        """AUTH-01 criterion 1: correct code within 5 minutes creates account."""
        now = timezone.now()
        with patch("accounts.services.patient_auth.send_sms") as mock_sms:
            challenge = request_registration_otp("+8801712345678", now=now)
            mock_sms.assert_called_once()

        user = complete_registration_with_otp(
            full_name="Rahima Akter",
            mobile_number="01712345678",
            entered_code=challenge.code,
            now=now + timedelta(minutes=4, seconds=59),
        )

        self.assertEqual(user.role, User.Role.PATIENT)
        self.assertFalse(user.has_usable_password())
        patient = Patient.objects.get(mobile_number="+8801712345678")
        self.assertEqual(patient.user, user)
        self.assertEqual(patient.full_name, "Rahima Akter")
        self.assertFalse(OtpChallenge.objects.filter(mobile_number="+8801712345678").exists())

    def test_registration_links_existing_reception_patient_without_login(self):
        """AUTH-01 + A-10: links to an existing walk-in Patient record with no user."""
        existing = Patient.objects.create(
            full_name="Karim Uddin",
            mobile_number="+8801812345678",
            approx_age=62,
        )
        now = timezone.now()
        with patch("accounts.services.patient_auth.send_sms"):
            challenge = request_registration_otp("+8801812345678", now=now)

        user = complete_registration_with_otp(
            full_name="Karim Uddin",
            mobile_number="+8801812345678",
            entered_code=challenge.code,
            now=now + timedelta(minutes=1),
        )

        existing.refresh_from_db()
        self.assertEqual(existing.user, user)
        self.assertEqual(Patient.objects.filter(mobile_number="+8801812345678").count(), 1)

    def test_expired_otp_is_refused(self):
        """AUTH-01 + SEC-04: code older than 5 minutes cannot complete registration."""
        now = timezone.now()
        with patch("accounts.services.patient_auth.send_sms"):
            challenge = request_registration_otp("+8801712345678", now=now)

        with self.assertRaises(ValidationError) as ctx:
            complete_registration_with_otp(
                full_name="Rahima Akter",
                mobile_number="+8801712345678",
                entered_code=challenge.code,
                now=now + timedelta(minutes=5, seconds=1),
            )
        self.assertIn("expired", " ".join(ctx.exception.messages).lower())

    def test_three_wrong_attempts_block_registration_for_15_minutes(self):
        """AUTH-01 criterion 2 + SEC-04: 3 wrong codes block for 15 minutes."""
        now = timezone.now()
        with patch("accounts.services.patient_auth.send_sms"):
            challenge = request_registration_otp("+8801712345678", now=now)

        wrong_code = "000000" if challenge.code != "000000" else "999999"
        last_error = None
        for attempt in range(3):
            with self.assertRaises(ValidationError) as ctx:
                complete_registration_with_otp(
                    full_name="Rahima Akter",
                    mobile_number="+8801712345678",
                    entered_code=wrong_code,
                    now=now + timedelta(seconds=10 * attempt),
                )
            last_error = ctx.exception

        self.assertIn("15 minutes", " ".join(last_error.messages))

        with self.assertRaises(ValidationError) as blocked_ctx:
            request_registration_otp("+8801712345678", now=now + timedelta(minutes=10))
        self.assertIn("15 minutes", " ".join(blocked_ctx.exception.messages))

        with patch("accounts.services.patient_auth.send_sms"):
            renewed = request_registration_otp("+8801712345678", now=now + timedelta(minutes=16))
        self.assertEqual(renewed.attempts_used, 0)


class PatientOtpLoginAndTimeoutTests(TestCase):
    """Tests for AUTH-02 patient OTP login and 30-minute inactivity timeout."""

    def setUp(self):
        """Create a registered patient with a User login."""
        self.user = User.objects.create_user(
            username="patient_8801912345678",
            role=User.Role.PATIENT,
        )
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        self.patient = Patient.objects.create(
            user=self.user,
            full_name="Nusrat Jahan",
            mobile_number="+8801912345678",
        )

    def test_registered_patient_logs_in_with_valid_otp(self):
        """AUTH-02 criterion 1: correct login OTP returns the patient user."""
        now = timezone.now()
        with patch("accounts.services.patient_auth.send_sms"):
            challenge = request_login_otp("+8801912345678", now=now)

        logged_in_user = verify_login_otp(
            "+8801912345678",
            challenge.code,
            now=now + timedelta(minutes=2),
        )
        self.assertEqual(logged_in_user, self.user)

    def test_end_to_end_patient_login_and_30_minute_inactivity_logout(self):
        """AUTH-02 criteria 1 & 2 + SEC-05: session expires after 30 min inactivity."""
        with patch("accounts.services.patient_auth.send_sms"):
            resp_step1 = self.client.post(
                reverse("accounts:patient_login"),
                {"mobile_number": "01912345678"},
            )
        self.assertRedirects(resp_step1, reverse("accounts:patient_login_verify"))

        challenge = OtpChallenge.objects.get(mobile_number="+8801912345678")
        resp_step2 = self.client.post(
            reverse("accounts:patient_login_verify"),
            {"code": challenge.code},
        )
        self.assertRedirects(resp_step2, reverse("accounts:home"))

        # Active click before 30 minutes succeeds.
        home_ok = self.client.get(reverse("accounts:home"))
        self.assertEqual(home_ok.status_code, 200)

        # Simulate 31 minutes of inactivity in the session.
        session = self.client.session
        session[LAST_ACTIVITY_SESSION_KEY] = time.time() - (31 * 60)
        session.save()

        expired_resp = self.client.get(reverse("accounts:home"))
        self.assertRedirects(expired_resp, reverse("accounts:patient_login"))
