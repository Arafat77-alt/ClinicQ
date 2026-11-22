"""Tests for emergencies, removals and returns (QUE-09, QUE-10, BR-08, BR-09, BR-10)."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from booking.models import Appointment
from scheduling.models import Doctor

from .models import QueueEntry
from .queue_actions import (
    emergency_alerts,
    flag_emergency,
    queue_board,
    remove_from_queue,
    return_to_queue,
)
from .services import add_to_queue, patients_ahead, waiting_queue

DHAKA = ZoneInfo("Asia/Dhaka")
START = datetime(2026, 11, 16, 17, 0, tzinfo=DHAKA)


class QueueActionTestCase(TestCase):
    """Shared set-up: one doctor with three walk-ins waiting (made-up people)."""

    def setUp(self):
        """Create the people and three waiting patients, 5 minutes apart."""
        self.now = START
        clock = patch("django.utils.timezone.now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.doctor_user = User.objects.create_user(
            username="d1", password="x", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user, code="D1", specialty="Medicine", room="101"
        )
        other_user = User.objects.create_user(username="d2", password="x", role=User.Role.DOCTOR)
        self.other_doctor = Doctor.objects.create(
            user=other_user, code="D2", specialty="Medicine", room="102"
        )
        self.receptionist = User.objects.create_user(
            username="shirin", password="x", role=User.Role.RECEPTIONIST
        )
        self.first = self.arrive("Karim Uddin", "+8801711000001")
        self.second = self.arrive("Salma Begum", "+8801711000002")
        self.third = self.arrive("Rafiq Islam", "+8801711000003")

    def arrive(self, name, number, doctor=None):
        """Add a walk-in to the queue and move the clock on by 5 minutes."""
        patient = Patient.objects.create(full_name=name, mobile_number=number)
        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor or self.doctor,
            type=Appointment.Type.WALKIN,
            status=Appointment.Status.CHECKED_IN,
        )
        entry = add_to_queue(appointment, check_in_time=self.now)
        self.now += timedelta(minutes=5)
        return entry

    def order(self):
        """Return the tokens of the waiting patients in calling order."""
        return [entry.token for entry in waiting_queue(self.doctor, START.date())]

    def make_to_decide(self, entry):
        """Pretend the doctor skipped this patient twice (QUE-08, Person D)."""
        entry.state = QueueEntry.State.RECEPTION_TO_DECIDE
        entry.skip_count = 2
        entry.save()
        return entry


class EmergencyTests(QueueActionTestCase):
    """QUE-09 and BR-09."""

    def test_reason_is_required(self):
        """An empty or blank reason is refused."""
        for reason in ("", "   "):
            with self.assertRaisesMessage(ValidationError, "A reason is required"):
                flag_emergency(self.third, self.receptionist, reason)
        self.third.refresh_from_db()
        self.assertFalse(self.third.is_emergency)

    def test_emergency_is_first_in_the_queue(self):
        """BR-08: emergencies come before everyone else."""
        flag_emergency(self.third, self.receptionist, "Chest pain")
        self.assertEqual(self.order(), ["D1-003", "D1-001", "D1-002"])
        self.assertEqual(patients_ahead(self.first), 1)

    def test_two_emergencies_are_ordered_by_the_time_they_were_flagged(self):
        """BR-09: the earliest flagged goes first, not the earliest arrival."""
        flag_emergency(self.third, self.receptionist, "Chest pain")
        self.now += timedelta(minutes=1)
        flag_emergency(self.second, self.doctor_user, "High fever, child")
        self.assertEqual(self.order(), ["D1-003", "D1-002", "D1-001"])

    def test_name_time_and_reason_are_stored(self):
        """SAFE-02: the action is recorded with who, when and why."""
        flag_emergency(self.second, self.receptionist, "  Chest pain  ")
        self.second.refresh_from_db()
        self.assertTrue(self.second.is_emergency)
        self.assertEqual(self.second.emergency_reason, "Chest pain")
        self.assertEqual(self.second.emergency_flagged_by, self.receptionist)
        self.assertEqual(self.second.emergency_flagged_at, self.now)

    def test_only_receptionists_and_doctors_can_flag(self):
        """BR-09: patients and the administrator cannot."""
        for role in (User.Role.PATIENT, User.Role.ADMIN):
            user = User.objects.create_user(username=f"x-{role}", password="x", role=role)
            with self.assertRaisesMessage(ValidationError, "Only a receptionist or a doctor"):
                flag_emergency(self.second, user, "Chest pain")

    def test_doctor_can_flag_only_in_their_own_queue(self):
        """A doctor cannot change another doctor's queue."""
        other_entry = self.arrive("Mina Das", "+8801711000009", doctor=self.other_doctor)
        with self.assertRaisesMessage(ValidationError, "only in your own queue"):
            flag_emergency(other_entry, self.doctor_user, "Chest pain")

    def test_patient_who_is_not_waiting_cannot_be_flagged(self):
        """Only waiting patients can jump the queue."""
        self.first.state = QueueEntry.State.IN_CONSULTATION
        self.first.save()
        with self.assertRaisesMessage(ValidationError, "Only a waiting patient"):
            flag_emergency(self.first, self.receptionist, "Chest pain")

    def test_flagging_twice_is_refused(self):
        """The first flag time is kept, so the order stays fair."""
        flag_emergency(self.second, self.receptionist, "Chest pain")
        with self.assertRaisesMessage(ValidationError, "already flagged"):
            flag_emergency(self.second, self.receptionist, "Again")

    def test_doctor_is_alerted(self):
        """QUE-09: the doctor sees the emergency in the alerts."""
        flag_emergency(self.third, self.receptionist, "Chest pain")
        self.assertEqual(emergency_alerts(self.doctor, START.date()), [self.third])
        board = queue_board(START.date(), doctor=self.doctor)
        self.assertEqual(board[0]["alerts"], [self.third])


class RemoveAndReturnTests(QueueActionTestCase):
    """QUE-10 and BR-10."""

    def test_reason_is_required_to_remove(self):
        """Nothing changes without a reason."""
        with self.assertRaisesMessage(ValidationError, "A reason is required"):
            remove_from_queue(self.first, self.receptionist, "")
        self.first.refresh_from_db()
        self.assertEqual(self.first.state, QueueEntry.State.WAITING)

    def test_removing_a_patient_moves_the_others_up(self):
        """QUE-10 step 1: positions update and the reason is stored."""
        self.assertEqual(patients_ahead(self.third), 2)
        remove_from_queue(self.first, self.receptionist, "Left clinic")
        self.assertEqual(patients_ahead(self.third), 1)
        self.assertEqual(self.order(), ["D1-002", "D1-003"])
        self.first.refresh_from_db()
        self.assertEqual(self.first.state, QueueEntry.State.REMOVED)
        self.assertEqual(self.first.removal_reason, "Left clinic")
        self.assertEqual(self.first.removed_by, self.receptionist)
        self.assertEqual(self.first.appointment.status, Appointment.Status.CANCELLED)

    def test_only_a_receptionist_can_remove(self):
        """QUE-10 is a receptionist story."""
        with self.assertRaisesMessage(ValidationError, "Only a receptionist"):
            remove_from_queue(self.first, self.doctor_user, "Left clinic")

    def test_patient_with_the_doctor_cannot_be_removed(self):
        """The doctor completes or skips the current patient instead (QUE-08)."""
        self.first.state = QueueEntry.State.IN_CONSULTATION
        self.first.save()
        with self.assertRaisesMessage(ValidationError, "cannot be removed here"):
            remove_from_queue(self.first, self.receptionist, "Left clinic")

    def test_patient_skipped_twice_can_be_returned_behind_everyone(self):
        """QUE-10 step 2 and BR-10: back to Waiting, at the end of the queue."""
        self.make_to_decide(self.first)
        self.assertEqual(self.order(), ["D1-002", "D1-003"])
        return_to_queue(self.first, self.receptionist)
        self.first.refresh_from_db()
        self.assertEqual(self.first.state, QueueEntry.State.WAITING)
        self.assertEqual(self.first.skip_count, 2)  # kept, so no third skip (QUE-08)
        self.assertEqual(self.order(), ["D1-002", "D1-003", "D1-001"])

    def test_patient_skipped_twice_can_be_removed(self):
        """QUE-10 step 2: the other choice."""
        self.make_to_decide(self.first)
        remove_from_queue(self.first, self.receptionist, "Did not answer twice")
        self.first.refresh_from_db()
        self.assertEqual(self.first.state, QueueEntry.State.REMOVED)

    def test_only_reception_to_decide_can_be_returned(self):
        """A waiting patient is already in the queue."""
        with self.assertRaisesMessage(ValidationError, "Only patients marked Reception to decide"):
            return_to_queue(self.first, self.receptionist)

    def test_board_shows_patients_for_reception_to_decide(self):
        """QUE-10 step 2: the receptionist sees them marked."""
        self.make_to_decide(self.first)
        board = queue_board(START.date())
        self.assertEqual(board[0]["to_decide"], [self.first])


class QueuePageTests(QueueActionTestCase):
    """The pages for QUE-09 and QUE-10."""

    def setUp(self):
        """Use the real clock date for pages, because they show today's queues."""
        super().setUp()
        self.now = START + timedelta(hours=1)

    def test_receptionist_flags_an_emergency_from_the_page(self):
        """The form saves the reason and goes back to the board."""
        self.client.force_login(self.receptionist)
        url = reverse("reception_queue:emergency", args=[self.third.pk])
        response = self.client.post(url, {"reason": "Chest pain"}, follow=True)
        self.assertContains(response, "is now an emergency")
        self.assertContains(response, "Emergency:")
        self.third.refresh_from_db()
        self.assertTrue(self.third.is_emergency)

    def test_empty_reason_on_the_page_shows_a_plain_message(self):
        """Rule 10: plain words."""
        self.client.force_login(self.receptionist)
        url = reverse("reception_queue:remove", args=[self.first.pk])
        response = self.client.post(url, {"reason": ""})
        self.assertContains(response, "A reason is required.")

    def test_doctor_cannot_open_another_doctors_patient(self):
        """SEC-01: a 403 page, not the patient's name."""
        other_entry = self.arrive("Mina Das", "+8801711000009", doctor=self.other_doctor)
        self.client.force_login(self.doctor_user)
        url = reverse("reception_queue:emergency", args=[other_entry.pk])
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_doctor_sees_only_their_own_queue(self):
        """The board for a doctor lists one queue."""
        self.arrive("Mina Das", "+8801711000009", doctor=self.other_doctor)
        self.client.force_login(self.doctor_user)
        response = self.client.get(reverse("reception_queue:board"))
        self.assertContains(response, "Karim Uddin")
        self.assertNotContains(response, "Mina Das")
        self.assertNotContains(response, ">Remove<")

    def test_doctor_cannot_remove_or_return(self):
        """QUE-10 pages are for receptionists only."""
        self.client.force_login(self.doctor_user)
        remove_url = reverse("reception_queue:remove", args=[self.first.pk])
        return_url = reverse("reception_queue:return", args=[self.first.pk])
        self.assertEqual(self.client.get(remove_url).status_code, 403)
        self.assertEqual(self.client.post(return_url).status_code, 403)

    def test_patient_cannot_open_the_board(self):
        """SEC-01."""
        patient_user = User.objects.create_user(username="p", password="x")
        self.client.force_login(patient_user)
        self.assertEqual(self.client.get(reverse("reception_queue:board")).status_code, 403)

    def test_receptionist_returns_a_patient_from_the_board(self):
        """The Return button works."""
        self.make_to_decide(self.first)
        self.client.force_login(self.receptionist)
        url = reverse("reception_queue:return", args=[self.first.pk])
        response = self.client.post(url, follow=True)
        self.assertContains(response, "is back in the queue")
