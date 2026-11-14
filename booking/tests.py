"""Tests for the booking application."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import Patient, User
from scheduling.models import Doctor

from .models import Appointment
from .services import generate_reference_number


class AppointmentTests(TestCase):
    """BKG-03, BR-01 and REL-02: appointments and the no-double-booking rule."""

    def setUp(self):
        """Create a doctor, two patients and one time slot."""
        doctor_user = User.objects.create_user(
            username="dr_imran", password="test-pass-123", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.create(
            user=doctor_user, code="D2", specialty="General", room="102"
        )
        self.patient_one = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678"
        )
        self.patient_two = Patient.objects.create(
            full_name="Karim Uddin", mobile_number="+8801812345678"
        )
        self.start = (timezone.now() + timedelta(days=1)).replace(
            minute=0, second=0, microsecond=0
        )
        self.end = self.start + timedelta(minutes=15)

    def book(self, patient, **extra):
        """Create an appointment in the shared slot unless told otherwise."""
        values = {
            "patient": patient,
            "doctor": self.doctor,
            "slot_start": self.start,
            "slot_end": self.end,
        }
        values.update(extra)
        return Appointment.objects.create(**values)

    def test_reference_number_is_created_automatically(self):
        """BKG-03: every appointment gets a reference number."""
        appointment = self.book(self.patient_one)
        self.assertTrue(appointment.reference_number.startswith("CQ-"))

    def test_database_blocks_double_booking(self):
        """REL-02: the database refuses a second active appointment in a slot."""
        self.book(self.patient_one)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.book(self.patient_two)

    def test_double_booking_message_is_clear(self):
        """USAB-06: say why the booking was refused and what to do."""
        self.book(self.patient_one)
        second = Appointment(
            patient=self.patient_two,
            doctor=self.doctor,
            slot_start=self.start,
            slot_end=self.end,
        )
        with self.assertRaises(ValidationError) as caught:
            second.full_clean()
        self.assertIn("already has an active appointment", str(caught.exception))

    def test_cancelled_appointment_frees_the_slot(self):
        """BR-01: a cancelled appointment no longer occupies the slot."""
        first = self.book(self.patient_one)
        first.status = Appointment.Status.CANCELLED
        first.save()
        second = self.book(self.patient_two)
        self.assertEqual(second.status, Appointment.Status.BOOKED)

    def test_online_appointment_needs_a_time_slot(self):
        """Only walk-ins may have no time slot."""
        appointment = Appointment(
            patient=self.patient_one, doctor=self.doctor, type=Appointment.Type.ONLINE
        )
        with self.assertRaises(ValidationError) as caught:
            appointment.full_clean()
        self.assertIn("needs a start and end time", str(caught.exception))

    def test_walk_in_does_not_need_a_time_slot(self):
        """QUE-03: a walk-in is registered without a booked slot."""
        walk_in = Appointment(
            patient=self.patient_one,
            doctor=self.doctor,
            type=Appointment.Type.WALKIN,
            status=Appointment.Status.CHECKED_IN,
        )
        walk_in.full_clean()
        walk_in.save()
        self.assertIsNone(walk_in.slot_start)

    def test_end_must_be_after_start(self):
        """The slot cannot end before it starts."""
        backwards = Appointment(
            patient=self.patient_one,
            doctor=self.doctor,
            slot_start=self.end,
            slot_end=self.start,
        )
        with self.assertRaises(ValidationError):
            backwards.full_clean()


class ReferenceNumberTests(TestCase):
    """The reference number must be easy to read out loud."""

    def test_format_and_length(self):
        """The number starts with CQ- and has 8 characters after it."""
        reference = generate_reference_number()
        self.assertTrue(reference.startswith("CQ-"))
        self.assertEqual(len(reference), 11)