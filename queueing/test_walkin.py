"""Tests for registering walk-in patients (QUE-03, BR-08, BR-14)."""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from booking.models import Appointment
from reports.services import schedule_for_day
from scheduling.models import Doctor

from .models import QueueEntry
from .walkin import find_or_create_walk_in_patient, register_walk_in

DHAKA = ZoneInfo("Asia/Dhaka")
NOW = datetime(2026, 11, 16, 17, 5, tzinfo=DHAKA)


class WalkInTestCase(TestCase):
    """Shared set-up: two doctors and a receptionist (made-up people)."""

    def setUp(self):
        """Create the people and freeze the clock at Monday 17:05."""
        self.doctor_one = self.make_doctor("d1", "D1")
        self.doctor_two = self.make_doctor("d2", "D2")
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def make_doctor(self, username, code):
        """Create a doctor account with a profile."""
        user = User.objects.create_user(
            username=username, password="Strong-pass-123", role=User.Role.DOCTOR
        )
        return Doctor.objects.create(user=user, code=code, specialty="Medicine", room="101")

    def walk_in(self, name, number, doctor):
        """Register a walk-in the way the page does, and return the queue entry."""
        patient, _created = find_or_create_walk_in_patient(name, number, 30)
        return register_walk_in(patient, doctor, self.receptionist)


class WalkInServiceTests(WalkInTestCase):
    """QUE-03 business rules."""

    def test_first_walk_in_gets_token_001(self):
        """BR-14: the first patient of the day is 001."""
        entry = self.walk_in("Karim Uddin", "01711000001", self.doctor_one)
        self.assertEqual(entry.token, "D1-001")

    def test_next_walk_in_for_the_same_doctor_gets_002(self):
        """BR-14: tokens count up per doctor."""
        self.walk_in("Karim Uddin", "01711000001", self.doctor_one)
        second = self.walk_in("Salma Begum", "01711000002", self.doctor_one)
        self.assertEqual(second.token, "D1-002")

    def test_another_doctor_starts_again_at_001(self):
        """BR-14: each doctor has their own numbers."""
        self.walk_in("Karim Uddin", "01711000001", self.doctor_one)
        other = self.walk_in("Salma Begum", "01711000002", self.doctor_two)
        self.assertEqual(other.token, "D2-001")

    def test_known_phone_number_reuses_the_existing_patient(self):
        """A-10: one number, one patient record."""
        existing = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678", approx_age=34
        )
        patient, created = find_or_create_walk_in_patient("Rahima Akter", "01712 345678", 34)
        self.assertEqual(patient, existing)
        self.assertFalse(created)
        self.assertEqual(Patient.objects.count(), 1)

    def test_dependent_with_matching_name_is_chosen(self):
        """When a family shares a number, the person whose name matches is used."""
        guardian = Patient.objects.create(full_name="Rahima Akter", mobile_number="+8801712345678")
        child = Patient.objects.create(
            full_name="Nabil Akter", mobile_number="+8801712345678", guardian=guardian
        )
        patient, created = find_or_create_walk_in_patient("nabil akter", "01712345678", 8)
        self.assertEqual(patient, child)
        self.assertFalse(created)

    def test_new_number_creates_a_patient(self):
        """An unknown number makes a new record with the age."""
        patient, created = find_or_create_walk_in_patient("Karim Uddin", "01711000001", 52)
        self.assertTrue(created)
        self.assertEqual(patient.mobile_number, "+8801711000001")
        self.assertEqual(patient.approx_age, 52)

    def test_wrong_number_is_refused_in_plain_words(self):
        """A number that is not Bangladeshi mobile shows the validator's message."""
        with self.assertRaisesMessage(ValidationError, "+8801XXXXXXXXX"):
            find_or_create_walk_in_patient("Karim Uddin", "12345", 52)

    def test_walk_in_appointment_has_no_slot_and_is_checked_in(self):
        """SRS 3.3: a walk-in starts at Checked-In, without a time slot."""
        entry = self.walk_in("Karim Uddin", "01711000001", self.doctor_one)
        appointment = entry.appointment
        self.assertEqual(appointment.type, Appointment.Type.WALKIN)
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)
        self.assertIsNone(appointment.slot_start)
        self.assertEqual(appointment.created_by, self.receptionist)
        self.assertEqual(entry.state, QueueEntry.State.WAITING)
        self.assertEqual(entry.effective_time, NOW)  # BR-08: walk-ins queue from arrival

    def test_same_patient_cannot_join_the_same_queue_twice(self):
        """A double click must not give two tokens."""
        entry = self.walk_in("Karim Uddin", "01711000001", self.doctor_one)
        with self.assertRaisesMessage(ValidationError, "D1-001"):
            register_walk_in(entry.appointment.patient, self.doctor_one, self.receptionist)
        self.assertEqual(QueueEntry.objects.count(), 1)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_inactive_doctor_is_refused(self):
        """A deactivated doctor takes no walk-ins."""
        self.doctor_one.is_active = False
        self.doctor_one.save()
        patient, _ = find_or_create_walk_in_patient("Karim Uddin", "01711000001", 52)
        with self.assertRaisesMessage(ValidationError, "not taking patients"):
            register_walk_in(patient, self.doctor_one, self.receptionist)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_walk_in_appears_on_the_printed_schedule(self):
        """SYS-04: walk-ins have no slot but are still printed for their day."""
        entry = self.walk_in("Karim Uddin", "01711000001", self.doctor_one)
        schedule = dict(schedule_for_day(date(2026, 11, 16)))
        self.assertEqual(schedule[self.doctor_one], [entry.appointment])


class WalkInPageTests(WalkInTestCase):
    """QUE-03 pages: 2 screens, receptionist only."""

    url = reverse("reception_queue:walk_in")

    def post(self, **changes):
        """Send the walk-in form with valid made-up data."""
        data = {
            "full_name": "Karim Uddin",
            "mobile_number": "01711000001",
            "age": 52,
            "doctor": self.doctor_two.pk,
            "reason": "Fever",
        }
        data.update(changes)
        return self.client.post(self.url, data, follow=True)

    def test_receptionist_registers_a_walk_in_and_sees_the_token(self):
        """One form, then the token page."""
        self.client.force_login(self.receptionist)
        response = self.post()
        self.assertContains(response, "D2-001")
        self.assertContains(response, "Nobody is waiting ahead.")
        self.assertEqual(QueueEntry.objects.get().appointment.reason, "Fever")

    def test_missing_doctor_shows_a_plain_message(self):
        """The receptionist is told what to do."""
        self.client.force_login(self.receptionist)
        response = self.post(doctor="")
        self.assertContains(response, "Choose the doctor the patient wants to see.")
        self.assertEqual(QueueEntry.objects.count(), 0)

    def test_inactive_doctor_is_not_offered(self):
        """Only active doctors are in the drop-down."""
        self.doctor_two.is_active = False
        self.doctor_two.save()
        self.client.force_login(self.receptionist)
        response = self.client.get(self.url)
        self.assertContains(response, "D1 - Dr.")
        self.assertNotContains(response, "D2 - Dr.")

    def test_other_roles_are_refused(self):
        """SEC-01: only receptionists register walk-ins."""
        for role in (User.Role.DOCTOR, User.Role.PATIENT, User.Role.ADMIN):
            user = User.objects.create_user(username=f"x-{role}", password="x", role=role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
