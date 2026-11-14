"""Tests for the scheduling application."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User

from .models import Doctor


class DoctorTests(TestCase):
    """SCH-01: doctor profiles."""

    def make_user(self, username, role):
        """Create a test account with the given role."""
        return User.objects.create_user(username=username, password="test-pass-123", role=role)

    def test_doctor_account_must_have_the_doctor_role(self):
        """A patient account cannot be used as a doctor."""
        patient_user = self.make_user("rahima", User.Role.PATIENT)
        doctor = Doctor(user=patient_user, code="D1", specialty="Cardiology", room="101")
        with self.assertRaises(ValidationError) as caught:
            doctor.full_clean()
        self.assertIn("does not have the doctor role", str(caught.exception))

    def test_doctor_code_must_be_unique_with_a_clear_message(self):
        """USAB-06: say why a duplicate code is refused and how to fix it."""
        first = self.make_user("imran", User.Role.DOCTOR)
        second = self.make_user("nadia", User.Role.DOCTOR)
        Doctor.objects.create(user=first, code="D2", specialty="General", room="102")
        duplicate = Doctor(user=second, code="D2", specialty="Skin", room="103")
        with self.assertRaises(ValidationError) as caught:
            duplicate.full_clean()
        self.assertIn("already used by another doctor", str(caught.exception))

    def test_doctor_code_must_start_with_d_and_a_number(self):
        """The code format must work in tokens such as D2-014 (BR-14)."""
        user = self.make_user("karim", User.Role.DOCTOR)
        doctor = Doctor(user=user, code="X9", specialty="General", room="104")
        with self.assertRaises(ValidationError):
            doctor.full_clean()

    def test_default_slot_length_is_15_minutes(self):
        """The default slot length is 15 minutes (SRS definitions)."""
        user = self.make_user("sultana", User.Role.DOCTOR)
        doctor = Doctor.objects.create(user=user, code="D3", specialty="Eye", room="105")
        self.assertEqual(doctor.default_slot_minutes, 15)
        self.assertTrue(doctor.is_active)