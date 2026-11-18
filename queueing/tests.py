"""Tests for the queueing application (BR-05, BR-08, BR-09, BR-10, BR-11, BR-14)."""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Patient, User
from booking.models import Appointment
from scheduling.models import Doctor

from .models import QueueEntry
from .services import (
    add_to_queue,
    effective_time_for,
    next_token_number,
    patients_ahead,
    waiting_queue,
)

DHAKA = ZoneInfo("Asia/Dhaka")
MONDAY = date(2026, 11, 16)


def at(hour, minute=0, day=16):
    """Return a Dhaka-time moment on the given day of November 2026."""
    return datetime(2026, 11, day, hour, minute, tzinfo=DHAKA)


class QueueTestCase(TestCase):
    """Shared set-up: two doctors and a helper that makes patients and appointments."""

    def setUp(self):
        """Create two doctors, D2 and D3."""
        self.doctor = self.make_doctor("imran", "D2", "Cardiology")
        self.other_doctor = self.make_doctor("nadia", "D3", "Skin")
        self.counter = 0

    def make_doctor(self, username, code, specialty):
        """Create a doctor account and profile."""
        user = User.objects.create_user(
            username=username, password="Strong-pass-123", role=User.Role.DOCTOR
        )
        return Doctor.objects.create(user=user, code=code, specialty=specialty, room="101")

    def make_appointment(self, doctor=None, start=None, kind=Appointment.Type.ONLINE, status=None):
        """Create a new patient with an appointment (or a walk-in when start is None)."""
        self.counter += 1
        patient = Patient.objects.create(
            full_name=f"Patient {self.counter}", mobile_number=f"+88017000000{self.counter:02d}"
        )
        if start is None:
            kind = Appointment.Type.WALKIN
        return Appointment.objects.create(
            patient=patient,
            doctor=doctor or self.doctor,
            slot_start=start,
            slot_end=start + timedelta(minutes=15) if start else None,
            type=kind,
            status=status or (
                Appointment.Status.CHECKED_IN if kind == Appointment.Type.WALKIN
                else Appointment.Status.BOOKED
            ),
        )

    def make_entry(self, token, state=QueueEntry.State.WAITING, doctor=None, queue_date=MONDAY, **extra):
        """Create a queue entry directly, for tests of constraints and ordering."""
        appointment = self.make_appointment(doctor=doctor)
        values = {
            "appointment": appointment,
            "doctor": appointment.doctor,
            "queue_date": queue_date,
            "token_number": token,
            "check_in_time": at(17, 0),
            "effective_time": at(17, 0),
            "state": state,
        }
        values.update(extra)
        return QueueEntry.objects.create(**values)


class TokenTests(QueueTestCase):
    """BR-14: tokens run 001, 002, ... per doctor per day."""

    def test_tokens_count_up_for_one_doctor(self):
        """The first patient gets 1 and the next gets 2."""
        first = add_to_queue(self.make_appointment(start=at(17)), at(16, 55))
        second = add_to_queue(self.make_appointment(start=at(17, 15)), at(17, 5))
        self.assertEqual([first.token_number, second.token_number], [1, 2])
        self.assertEqual(first.token, "D2-001")

    def test_token_shows_three_digits_with_the_doctor_code(self):
        """Token 14 for doctor D2 is shown as D2-014."""
        entry = self.make_entry(14)
        self.assertEqual(entry.token, "D2-014")

    def test_each_doctor_has_their_own_numbers(self):
        """Another doctor starts again at 1."""
        add_to_queue(self.make_appointment(start=at(17)), at(16, 55))
        other = add_to_queue(self.make_appointment(self.other_doctor, at(17)), at(16, 55))
        self.assertEqual(other.token, "D3-001")

    def test_numbers_start_again_every_day(self):
        """A new day starts at 1."""
        add_to_queue(self.make_appointment(start=at(17)), at(16, 55))
        next_day = add_to_queue(self.make_appointment(start=at(17, day=17)), at(16, 55, day=17))
        self.assertEqual(next_day.token_number, 1)
        self.assertEqual(next_token_number(self.doctor, date(2026, 11, 18)), 1)

    def test_the_day_is_the_day_in_dhaka(self):
        """1 AM on 16 November in Dhaka is still 15 November in UTC."""
        moment = datetime(2026, 11, 15, 19, 0, tzinfo=dt_timezone.utc)
        entry = add_to_queue(self.make_appointment(start=None), moment)
        self.assertEqual(entry.queue_date, date(2026, 11, 16))

    def test_a_token_taken_a_moment_ago_is_skipped(self):
        """Two check-ins at the same moment still get different tokens."""
        self.make_entry(1)
        appointment = self.make_appointment(start=at(17, 15))
        with patch("queueing.services.next_token_number", side_effect=[1, 2]):
            entry = add_to_queue(appointment, at(17, 10))
        self.assertEqual(entry.token_number, 2)

    def test_duplicate_token_is_refused_by_the_database(self):
        """The same token twice for one doctor and day cannot exist."""
        self.make_entry(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_entry(1)


class EffectiveTimeTests(QueueTestCase):
    """BR-05 and BR-08: the time used to order the queue."""

    def test_on_time_arrival_keeps_the_slot_start(self):
        """Arriving before the slot starts keeps the slot start."""
        appointment = self.make_appointment(start=at(17))
        self.assertEqual(effective_time_for(appointment, at(16, 55)), at(17))

    def test_very_early_arrival_keeps_the_slot_start(self):
        """An early patient does not jump ahead of earlier slots."""
        appointment = self.make_appointment(start=at(17))
        self.assertEqual(effective_time_for(appointment, at(16, 30)), at(17))

    def test_arrival_at_the_end_of_the_grace_period_keeps_the_slot_start(self):
        """Slot start plus 15 minutes is still on time."""
        appointment = self.make_appointment(start=at(17))
        self.assertEqual(effective_time_for(appointment, at(17, 15)), at(17))

    def test_late_arrival_joins_from_the_check_in_time(self):
        """After the grace period the patient joins from their check-in time."""
        appointment = self.make_appointment(start=at(17))
        self.assertEqual(effective_time_for(appointment, at(17, 20)), at(17, 20))

    def test_walk_in_joins_from_the_check_in_time(self):
        """A walk-in has no slot."""
        walk_in = self.make_appointment(start=None)
        self.assertEqual(effective_time_for(walk_in, at(17, 5)), at(17, 5))


class AddToQueueTests(QueueTestCase):
    """QUE-01 and QUE-03: joining the queue."""

    def test_check_in_creates_the_entry_and_updates_the_appointment(self):
        """The patient is waiting, with a token, and the appointment is Checked-In."""
        appointment = self.make_appointment(start=at(17))
        entry = add_to_queue(appointment, at(16, 55))
        appointment.refresh_from_db()
        self.assertEqual(entry.state, QueueEntry.State.WAITING)
        self.assertEqual(entry.queue_date, MONDAY)
        self.assertEqual(entry.check_in_time, at(16, 55))
        self.assertEqual(entry.effective_time, at(17))
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)

    def test_a_walk_in_can_join_without_a_time_slot(self):
        """QUE-03: a walk-in is already Checked-In and has no slot."""
        entry = add_to_queue(self.make_appointment(start=None), at(17, 5))
        self.assertEqual(entry.effective_time, at(17, 5))

    def test_the_same_patient_cannot_join_twice(self):
        """A clear message tells reception to look at the queue."""
        appointment = self.make_appointment(start=at(17))
        add_to_queue(appointment, at(16, 55))
        with self.assertRaises(ValidationError) as caught:
            add_to_queue(appointment, at(16, 56))
        self.assertIn("already in the queue", str(caught.exception))

    def test_a_cancelled_appointment_cannot_join(self):
        """Only booked appointments and walk-ins can check in."""
        appointment = self.make_appointment(start=at(17), status=Appointment.Status.CANCELLED)
        with self.assertRaises(ValidationError) as caught:
            add_to_queue(appointment, at(16, 55))
        self.assertIn("cancelled", str(caught.exception))
        self.assertFalse(QueueEntry.objects.exists())


class QueueOrderTests(QueueTestCase):
    """BR-08: emergencies first, then effective time, then check-in time."""

    def test_order_follows_the_effective_time(self):
        """An on-time appointment, a walk-in and a later appointment."""
        late_slot = add_to_queue(self.make_appointment(start=at(17, 15)), at(16, 50))
        walk_in = add_to_queue(self.make_appointment(start=None), at(17, 5))
        first_slot = add_to_queue(self.make_appointment(start=at(17)), at(17, 10))
        order = waiting_queue(self.doctor, MONDAY)
        self.assertEqual(order, [first_slot, walk_in, late_slot])

    def test_equal_effective_times_are_ordered_by_check_in_time(self):
        """A walk-in arriving at 17:15 ties with the 17:15 appointment; the earlier arrival wins."""
        walk_in = add_to_queue(self.make_appointment(start=None), at(17, 15))
        booked = add_to_queue(self.make_appointment(start=at(17, 15)), at(17, 10))
        self.assertEqual(walk_in.effective_time, booked.effective_time)
        self.assertEqual(waiting_queue(self.doctor, MONDAY), [booked, walk_in])

    def test_an_emergency_goes_first(self):
        """BR-09: an emergency is ahead of everybody else."""
        add_to_queue(self.make_appointment(start=at(17)), at(16, 55))
        urgent = add_to_queue(self.make_appointment(start=None), at(17, 30))
        urgent.is_emergency = True
        urgent.emergency_reason = "Chest pain"
        urgent.emergency_flagged_at = at(17, 31)
        urgent.save()
        self.assertEqual(waiting_queue(self.doctor, MONDAY)[0], urgent)

    def test_several_emergencies_are_ordered_by_the_time_they_were_flagged(self):
        """BR-09: the earliest flagged emergency is first."""
        first = add_to_queue(self.make_appointment(start=None), at(17, 30))
        second = add_to_queue(self.make_appointment(start=None), at(17, 20))
        for entry, flagged in ((first, at(17, 40)), (second, at(17, 45))):
            entry.is_emergency = True
            entry.emergency_reason = "Urgent"
            entry.emergency_flagged_at = flagged
            entry.save()
        self.assertEqual(waiting_queue(self.doctor, MONDAY)[:2], [first, second])

    def test_only_waiting_patients_are_listed(self):
        """A called patient is no longer in the waiting list."""
        waiting = add_to_queue(self.make_appointment(start=at(17)), at(16, 55))
        called = add_to_queue(self.make_appointment(start=at(17, 15)), at(17, 10))
        called.state = QueueEntry.State.CALLED
        called.save()
        self.assertEqual(waiting_queue(self.doctor, MONDAY), [waiting])

    def test_other_doctors_and_other_days_are_not_mixed_in(self):
        """Each doctor and each day has a separate queue."""
        mine = add_to_queue(self.make_appointment(start=at(17)), at(16, 55))
        add_to_queue(self.make_appointment(self.other_doctor, at(17)), at(16, 55))
        add_to_queue(self.make_appointment(start=at(17, day=17)), at(16, 55, day=17))
        self.assertEqual(waiting_queue(self.doctor, MONDAY), [mine])

    def test_patients_ahead_counts_the_people_to_be_called_first(self):
        """QUE-04: the third patient in line has two patients ahead."""
        a = add_to_queue(self.make_appointment(start=at(17)), at(16, 55))
        b = add_to_queue(self.make_appointment(start=at(17, 15)), at(17, 5))
        c = add_to_queue(self.make_appointment(start=at(17, 30)), at(17, 20))
        self.assertEqual([patients_ahead(a), patients_ahead(b), patients_ahead(c)], [0, 1, 2])


class QueueRuleConstraintTests(QueueTestCase):
    """The database itself enforces the queue rules."""

    def test_a_doctor_cannot_have_two_active_patients(self):
        """BR-11: one patient is called or in consultation at a time."""
        self.make_entry(1, state=QueueEntry.State.IN_CONSULTATION)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_entry(2, state=QueueEntry.State.CALLED)

    def test_the_active_patient_message_is_clear(self):
        """USAB-06: say what to do first."""
        self.make_entry(1, state=QueueEntry.State.CALLED)
        second = self.make_entry(2)
        second.state = QueueEntry.State.CALLED
        with self.assertRaises(ValidationError) as caught:
            second.full_clean()
        self.assertIn("Complete or skip that patient", str(caught.exception))

    def test_another_doctor_can_have_their_own_active_patient(self):
        """The rule is per doctor."""
        self.make_entry(1, state=QueueEntry.State.IN_CONSULTATION)
        entry = self.make_entry(1, state=QueueEntry.State.CALLED, doctor=self.other_doctor)
        self.assertEqual(entry.state, QueueEntry.State.CALLED)

    def test_a_completed_patient_does_not_count_as_active(self):
        """After completing, the doctor can call the next patient."""
        self.make_entry(1, state=QueueEntry.State.COMPLETED)
        self.assertTrue(self.make_entry(2, state=QueueEntry.State.CALLED).pk)

    def test_a_patient_cannot_be_skipped_more_than_twice(self):
        """BR-10: three skips are refused."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_entry(1, skip_count=3)
        self.assertTrue(self.make_entry(2, skip_count=2).pk)

    def test_an_emergency_needs_a_reason(self):
        """BR-09: the reason is required, with a clear message."""
        entry = self.make_entry(1)
        entry.is_emergency = True
        with self.assertRaises(ValidationError) as caught:
            entry.full_clean()
        self.assertIn("An emergency needs a reason", str(caught.exception))
        with self.assertRaises(IntegrityError), transaction.atomic():
            entry.save()

    def test_removing_a_patient_needs_a_reason(self):
        """QUE-10: the reason is required, with a clear message."""
        entry = self.make_entry(1)
        entry.state = QueueEntry.State.REMOVED
        with self.assertRaises(ValidationError) as caught:
            entry.full_clean()
        self.assertIn("Removing a patient needs a reason", str(caught.exception))
        entry.removal_reason = "Left the clinic"
        entry.full_clean()