"""Tests for doctor leave (SCH-03, BR-13)."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from booking.availability import free_slots
from booking.models import Appointment

from .leave import add_leave
from .models import Doctor, DoctorLeave, ScheduleRule
from .services import generate_slots

DHAKA = ZoneInfo("Asia/Dhaka")
# A Sunday morning. Monday is 16 November 2026, Tuesday is 17 November 2026.
SUNDAY_MORNING = datetime(2026, 11, 15, 10, 0, tzinfo=DHAKA)
MONDAY = date(2026, 11, 16)
TUESDAY = date(2026, 11, 17)
WEDNESDAY = date(2026, 11, 18)
NEXT_MONDAY = date(2026, 11, 23)


class LeaveTestCase(TestCase):
    """Shared set-up: a doctor who works Monday and Tuesday evenings."""

    def setUp(self):
        """Create the doctor, two patients and the weekly sessions."""
        self.user = User.objects.create_user(
            username="imran",
            password="Strong-pass-123",
            role=User.Role.DOCTOR,
            first_name="Imran",
            last_name="Hossain",
        )
        self.doctor = Doctor.objects.create(
            user=self.user, code="D1", specialty="Cardiology", room="101"
        )
        for weekday in (ScheduleRule.Weekday.MONDAY, ScheduleRule.Weekday.TUESDAY):
            ScheduleRule.objects.create(
                doctor=self.doctor,
                weekday=weekday,
                start_time=time(17, 0),
                end_time=time(21, 0),
                slot_minutes=15,
            )
        self.rahima = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678"
        )
        self.karim = Patient.objects.create(
            full_name="Karim Uddin", mobile_number="+8801812345678"
        )

    def clock(self):
        """Pretend that it is Sunday morning, 15 November 2026."""
        return patch("django.utils.timezone.now", return_value=SUNDAY_MORNING)

    def book(self, patient, day, hour, minute=0, status=Appointment.Status.BOOKED):
        """Create an appointment for a patient on the given day and time."""
        start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=DHAKA)
        return Appointment.objects.create(
            patient=patient,
            doctor=self.doctor,
            slot_start=start,
            slot_end=start + timedelta(minutes=15),
            status=status,
        )


class LeaveSlotTests(LeaveTestCase):
    """SCH-03 confirmation 1: no slots are offered during the leave."""

    def test_whole_days_of_leave_remove_all_slots_on_those_days(self):
        """Leave on Monday and Tuesday leaves no slots on either day."""
        DoctorLeave.objects.create(doctor=self.doctor, start_date=MONDAY, end_date=TUESDAY)
        self.assertEqual(generate_slots(self.doctor, MONDAY), [])
        self.assertEqual(generate_slots(self.doctor, TUESDAY), [])

    def test_days_after_the_leave_are_not_affected(self):
        """The next Monday still has its 16 slots."""
        DoctorLeave.objects.create(doctor=self.doctor, start_date=MONDAY, end_date=TUESDAY)
        self.assertEqual(len(generate_slots(self.doctor, NEXT_MONDAY)), 16)

    def test_leave_of_a_few_hours_removes_only_those_slots(self):
        """Leave from 17:00 to 19:00 removes 8 slots and keeps the other 8."""
        DoctorLeave.objects.create(
            doctor=self.doctor,
            start_date=MONDAY,
            end_date=MONDAY,
            start_time=time(17, 0),
            end_time=time(19, 0),
        )
        slots = generate_slots(self.doctor, MONDAY)
        self.assertEqual(len(slots), 8)
        self.assertEqual(slots[0][0], datetime(2026, 11, 16, 19, 0, tzinfo=DHAKA))

    def test_patients_and_reception_no_longer_see_the_slots(self):
        """The free times pages hide the days of leave for everyone."""
        add_leave_args = (self.doctor, MONDAY, TUESDAY)
        with self.clock():
            add_leave(*add_leave_args)
            patient_days = [str(day) for day, _ in free_slots(self.doctor, now=SUNDAY_MORNING)]
            reception_days = [
                str(day)
                for day, _ in free_slots(self.doctor, now=SUNDAY_MORNING, reception=True)
            ]
        self.assertNotIn("2026-11-16", patient_days)
        self.assertNotIn("2026-11-17", patient_days)
        self.assertNotIn("2026-11-16", reception_days)
        self.assertIn("2026-11-23", patient_days)

    def test_removing_the_leave_brings_the_slots_back(self):
        """Slots are offered again when the leave is removed."""
        leave = DoctorLeave.objects.create(doctor=self.doctor, start_date=MONDAY, end_date=MONDAY)
        self.assertEqual(generate_slots(self.doctor, MONDAY), [])
        leave.delete()
        self.assertEqual(len(generate_slots(self.doctor, MONDAY)), 16)


class AddLeaveTests(LeaveTestCase):
    """SCH-03 confirmation 1: appointments are moved and patients are told."""

    def test_booked_appointments_in_the_leave_need_rescheduling(self):
        """Existing appointments become Needs rescheduling (BR-13)."""
        inside = self.book(self.rahima, MONDAY, 17)
        also_inside = self.book(self.karim, TUESDAY, 18)
        outside = self.book(self.rahima, NEXT_MONDAY, 17)
        with self.clock(), patch("scheduling.leave.send_sms", return_value=True):
            result = add_leave(self.doctor, MONDAY, TUESDAY)
        for appointment in (inside, also_inside, outside):
            appointment.refresh_from_db()
        self.assertEqual(inside.status, Appointment.Status.NEEDS_RESCHEDULING)
        self.assertEqual(also_inside.status, Appointment.Status.NEEDS_RESCHEDULING)
        self.assertEqual(outside.status, Appointment.Status.BOOKED)
        self.assertEqual(len(result.rescheduled), 2)

    def test_only_booked_appointments_are_moved(self):
        """Cancelled and completed appointments are left alone."""
        cancelled = self.book(self.rahima, MONDAY, 17, status=Appointment.Status.CANCELLED)
        completed = self.book(self.karim, MONDAY, 18, status=Appointment.Status.COMPLETED)
        with self.clock(), patch("scheduling.leave.send_sms", return_value=True):
            result = add_leave(self.doctor, MONDAY, MONDAY)
        cancelled.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(cancelled.status, Appointment.Status.CANCELLED)
        self.assertEqual(completed.status, Appointment.Status.COMPLETED)
        self.assertEqual(result.rescheduled, [])

    def test_leave_of_a_few_hours_moves_only_appointments_inside_it(self):
        """An appointment at 20:00 is not affected by leave from 17:00 to 19:00."""
        inside = self.book(self.rahima, MONDAY, 17, 30)
        later = self.book(self.karim, MONDAY, 20)
        with self.clock(), patch("scheduling.leave.send_sms", return_value=True):
            add_leave(self.doctor, MONDAY, MONDAY, time(17, 0), time(19, 0))
        inside.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(inside.status, Appointment.Status.NEEDS_RESCHEDULING)
        self.assertEqual(later.status, Appointment.Status.BOOKED)

    def test_each_affected_patient_gets_a_text_message(self):
        """NOT-03: the message names the doctor, the reference and the old time."""
        appointment = self.book(self.rahima, MONDAY, 17)
        with self.clock(), patch("scheduling.leave.send_sms", return_value=True) as sender:
            add_leave(self.doctor, MONDAY, MONDAY)
        sender.assert_called_once()
        number, message = sender.call_args.args
        self.assertEqual(number, "+8801712345678")
        self.assertIn("Dr. Imran Hossain", message)
        self.assertIn(appointment.reference_number, message)
        self.assertIn("16 Nov 2026 at 17:00", message)
        self.assertIn("needs a new time", message)

    def test_a_failed_message_does_not_stop_the_leave(self):
        """REL-02/REL-04: the leave is saved and the failed patient is listed."""
        self.book(self.rahima, MONDAY, 17)
        second = self.book(self.karim, MONDAY, 18)

        def flaky(number, message):
            """Fail for the first patient only."""
            if number == "+8801712345678":
                raise ConnectionError("provider down")
            return True

        with self.clock(), patch("scheduling.leave.send_sms", side_effect=flaky):
            result = add_leave(self.doctor, MONDAY, MONDAY)
        self.assertTrue(DoctorLeave.objects.filter(pk=result.leave.pk).exists())
        self.assertEqual([a.patient for a in result.failed_notices], [self.rahima])
        second.refresh_from_db()
        self.assertEqual(second.status, Appointment.Status.NEEDS_RESCHEDULING)


class LeaveValidationTests(LeaveTestCase):
    """USAB-06: plain-language messages when the leave does not make sense."""

    def refuse(self, *args):
        """Return the message of the error raised for the given leave."""
        with self.clock():
            with self.assertRaises(ValidationError) as caught:
                add_leave(self.doctor, *args)
        return str(caught.exception)

    def test_last_day_before_first_day_is_refused(self):
        """The dates must be in order."""
        self.assertIn("cannot be before the first day", self.refuse(TUESDAY, MONDAY))

    def test_hours_need_both_a_start_and_an_end(self):
        """One time alone is not enough."""
        self.assertIn("both a start time and an end time", self.refuse(MONDAY, MONDAY, time(17, 0)))

    def test_hours_must_be_on_one_day(self):
        """Leave for hours cannot stretch over several days."""
        message = self.refuse(MONDAY, TUESDAY, time(17, 0), time(19, 0))
        self.assertIn("can only be on one day", message)

    def test_end_time_must_be_after_start_time(self):
        """The hours must make sense."""
        message = self.refuse(MONDAY, MONDAY, time(19, 0), time(17, 0))
        self.assertIn("end time must be after the start time", message)

    def test_leave_that_is_already_over_is_refused(self):
        """Nothing to save for the past."""
        message = self.refuse(date(2026, 11, 10), date(2026, 11, 12))
        self.assertIn("already over", message)

    def test_overlapping_leave_is_refused(self):
        """Two leaves cannot cover the same time."""
        with self.clock():
            add_leave(self.doctor, MONDAY, TUESDAY)
        message = self.refuse(TUESDAY, WEDNESDAY)
        self.assertIn("overlaps your leave", message)


class LeavePageTests(LeaveTestCase):
    """SCH-03 and SEC-01: the doctor's own leave page."""

    def log_in(self):
        """Log in as the doctor."""
        self.client.login(username="imran", password="Strong-pass-123")

    def form_data(self, **extra):
        """Return the form values for leave on Monday and Tuesday."""
        data = {"start_date": "2026-11-16", "end_date": "2026-11-17", "reason": "Conference"}
        data.update(extra)
        return data

    def test_anonymous_visitor_is_sent_to_login(self):
        """People who are not logged in cannot see the page."""
        self.assertEqual(self.client.get(reverse("scheduling:leave_list")).status_code, 302)

    def test_receptionist_cannot_open_the_page(self):
        """SEC-01: only doctors set their own leave."""
        User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )
        self.client.login(username="shirin", password="Strong-pass-123")
        self.assertEqual(self.client.get(reverse("scheduling:leave_list")).status_code, 403)

    def test_doctor_saves_leave_and_sees_what_changed(self):
        """SCH-03 confirmation: saved, appointments moved, patients told."""
        self.book(self.rahima, MONDAY, 17)
        self.log_in()
        with self.clock(), patch("scheduling.leave.send_sms", return_value=True):
            response = self.client.post(reverse("scheduling:leave_list"), self.form_data())
            page = self.client.get(reverse("scheduling:leave_list"))
        self.assertRedirects(
            response, reverse("scheduling:leave_list"), fetch_redirect_response=False
        )
        self.assertTrue(DoctorLeave.objects.filter(doctor=self.doctor).exists())
        self.assertContains(page, "1 appointment needs a new time")
        self.assertContains(page, "16 Nov 2026 to 17 Nov 2026")

    def test_failed_message_is_reported_to_the_doctor(self):
        """The doctor is told who could not be messaged."""
        self.book(self.rahima, MONDAY, 17)
        self.log_in()
        with self.clock(), patch("scheduling.leave.send_sms", side_effect=ConnectionError):
            self.client.post(reverse("scheduling:leave_list"), self.form_data())
            page = self.client.get(reverse("scheduling:leave_list"))
        self.assertContains(page, "could not be sent to: Rahima Akter")

    def test_page_shows_the_reason_when_the_dates_are_wrong(self):
        """USAB-06: the page explains what to fix."""
        self.log_in()
        with self.clock():
            response = self.client.post(
                reverse("scheduling:leave_list"),
                self.form_data(start_date="2026-11-18", end_date="2026-11-16"),
            )
        self.assertContains(response, "cannot be before the first day")
        self.assertFalse(DoctorLeave.objects.exists())

    def test_doctor_can_remove_their_own_leave(self):
        """Removing a leave opens the slots again."""
        leave = DoctorLeave.objects.create(doctor=self.doctor, start_date=MONDAY, end_date=MONDAY)
        self.log_in()
        self.client.post(reverse("scheduling:leave_delete", args=[leave.pk]))
        self.assertFalse(DoctorLeave.objects.filter(pk=leave.pk).exists())

    def test_doctor_cannot_remove_another_doctors_leave(self):
        """SEC-01: one doctor cannot change another doctor's leave."""
        other_user = User.objects.create_user(
            username="nadia", password="Strong-pass-123", role=User.Role.DOCTOR
        )
        other = Doctor.objects.create(user=other_user, code="D2", specialty="Skin", room="102")
        leave = DoctorLeave.objects.create(doctor=other, start_date=MONDAY, end_date=MONDAY)
        self.log_in()
        response = self.client.post(reverse("scheduling:leave_delete", args=[leave.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(DoctorLeave.objects.filter(pk=leave.pk).exists())