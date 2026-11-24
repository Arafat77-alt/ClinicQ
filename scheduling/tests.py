"""Tests for the scheduling application."""

from datetime import date, time

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Doctor, ScheduleBreak, ScheduleRule
from .services import generate_slots, slot_windows


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


class SlotTests(TestCase):
    """SCH-02: weekly sessions are cut into bookable slots."""

    def setUp(self):
        """Create a doctor with a Monday evening session."""
        user = User.objects.create_user(
            username="imran", password="Strong-pass-123", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.create(user=user, code="D2", specialty="General", room="102")
        self.monday_session = ScheduleRule.objects.create(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.MONDAY,
            start_time=time(17, 0),
            end_time=time(21, 0),
            slot_minutes=15,
        )
        self.a_monday = date(2026, 11, 16)
        self.a_tuesday = date(2026, 11, 17)

    def test_monday_evening_gives_16_slots(self):
        """SCH-02 confirmation 1: 17:00-21:00 with 15-minute slots is 16 slots."""
        windows = slot_windows(self.monday_session)
        self.assertEqual(len(windows), 16)
        self.assertEqual(windows[0], (time(17, 0), time(17, 15)))
        self.assertEqual(windows[-1], (time(20, 45), time(21, 0)))

    def test_slots_repeat_on_every_monday(self):
        """The same 16 slots are offered on any Monday, with Dhaka times."""
        slots = generate_slots(self.doctor, self.a_monday)
        self.assertEqual(len(slots), 16)
        self.assertEqual(slots[0][0].utcoffset().total_seconds(), 6 * 3600)
        self.assertEqual(len(generate_slots(self.doctor, date(2026, 11, 23))), 16)

    def test_no_slots_on_other_days(self):
        """A Tuesday has no session, so no slots are offered."""
        self.assertEqual(generate_slots(self.doctor, self.a_tuesday), [])

    def test_break_removes_two_slots(self):
        """SCH-02 confirmation 2: a 19:00-19:30 break removes 2 slots."""
        ScheduleBreak.objects.create(
            rule=self.monday_session, start_time=time(19, 0), end_time=time(19, 30)
        )
        windows = slot_windows(self.monday_session)
        self.assertEqual(len(windows), 14)
        self.assertNotIn((time(19, 0), time(19, 15)), windows)
        self.assertNotIn((time(19, 15), time(19, 30)), windows)
        self.assertIn((time(18, 45), time(19, 0)), windows)
        self.assertIn((time(19, 30), time(19, 45)), windows)

    def test_a_short_break_removes_every_slot_it_overlaps(self):
        """A 10-minute break that falls across two slots removes both of them."""
        ScheduleBreak.objects.create(
            rule=self.monday_session, start_time=time(19, 10), end_time=time(19, 20)
        )
        windows = slot_windows(self.monday_session)
        self.assertEqual(len(windows), 14)

    def test_inactive_doctor_offers_no_slots(self):
        """A deactivated doctor takes no new appointments."""
        self.doctor.is_active = False
        self.doctor.save()
        self.assertEqual(generate_slots(self.doctor, self.a_monday), [])

    def test_morning_and_evening_sessions_on_one_day(self):
        """Two sessions that do not overlap are allowed on the same day."""
        morning = ScheduleRule(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.MONDAY,
            start_time=time(9, 0),
            end_time=time(10, 0),
            slot_minutes=15,
        )
        morning.full_clean()
        morning.save()
        self.assertEqual(len(generate_slots(self.doctor, self.a_monday)), 20)

    def test_overlapping_session_is_refused_with_a_clear_message(self):
        """USAB-06: say which session overlaps and what to do."""
        clash = ScheduleRule(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.MONDAY,
            start_time=time(20, 0),
            end_time=time(22, 0),
            slot_minutes=15,
        )
        with self.assertRaises(ValidationError) as caught:
            clash.full_clean()
        self.assertIn("overlaps your Monday session from 17:00 to 21:00", str(caught.exception))

    def test_end_time_must_be_after_start_time(self):
        """A session cannot end before it starts."""
        backwards = ScheduleRule(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.TUESDAY,
            start_time=time(21, 0),
            end_time=time(17, 0),
            slot_minutes=15,
        )
        with self.assertRaises(ValidationError) as caught:
            backwards.full_clean()
        self.assertIn("end time must be after the start time", str(caught.exception))

    def test_session_shorter_than_one_slot_is_refused(self):
        """A 10-minute session cannot hold a 15-minute slot."""
        tiny = ScheduleRule(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.TUESDAY,
            start_time=time(9, 0),
            end_time=time(9, 10),
            slot_minutes=15,
        )
        with self.assertRaises(ValidationError) as caught:
            tiny.full_clean()
        self.assertIn("shorter than one 15-minute slot", str(caught.exception))

    def test_break_must_be_inside_its_session(self):
        """A break outside the working hours is refused with a clear message."""
        outside = ScheduleBreak(
            rule=self.monday_session, start_time=time(15, 0), end_time=time(15, 30)
        )
        with self.assertRaises(ValidationError) as caught:
            outside.full_clean()
        self.assertIn("must be inside the session", str(caught.exception))


class AvailabilityPageTests(TestCase):
    """SCH-02 and SEC-01: the doctor's own pages."""

    def setUp(self):
        """Create two doctors and a receptionist."""
        self.user = User.objects.create_user(
            username="imran", password="Strong-pass-123", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.create(
            user=self.user, code="D2", specialty="General", room="102"
        )
        other_user = User.objects.create_user(
            username="nadia", password="Strong-pass-123", role=User.Role.DOCTOR
        )
        self.other_doctor = Doctor.objects.create(
            user=other_user, code="D3", specialty="Skin", room="103"
        )
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )

    def log_in_as_doctor(self):
        """Log in as the first doctor."""
        self.client.login(username="imran", password="Strong-pass-123")

    def add_monday_session(self):
        """Send the add-session form for Monday 17:00 to 21:00."""
        return self.client.post(
            reverse("scheduling:rule_add"),
            {"weekday": 0, "start_time": "17:00", "end_time": "21:00", "slot_minutes": 15},
        )

    def test_anonymous_visitor_is_sent_to_login(self):
        """People who are not logged in cannot see the page."""
        response = self.client.get(reverse("scheduling:availability"))
        self.assertEqual(response.status_code, 302)

    def test_receptionist_cannot_open_the_page(self):
        """SEC-01: only doctors set their availability."""
        self.client.login(username="shirin", password="Strong-pass-123")
        response = self.client.get(reverse("scheduling:availability"))
        self.assertEqual(response.status_code, 403)

    def test_doctor_adds_a_session_and_sees_the_slot_count(self):
        """SCH-02 confirmation 1, through the real pages."""
        self.log_in_as_doctor()
        response = self.add_monday_session()
        self.assertRedirects(response, reverse("scheduling:availability"))
        self.assertTrue(ScheduleRule.objects.filter(doctor=self.doctor, weekday=0).exists())
        page = self.client.get(reverse("scheduling:availability"))
        self.assertContains(page, "16 slots every week")

    def test_doctor_adds_a_break_and_two_slots_disappear(self):
        """SCH-02 confirmation 2, through the real pages."""
        self.log_in_as_doctor()
        self.add_monday_session()
        rule = ScheduleRule.objects.get(doctor=self.doctor)
        response = self.client.post(
            reverse("scheduling:break_add", args=[rule.pk]),
            {"start_time": "19:00", "end_time": "19:30"},
        )
        self.assertRedirects(response, reverse("scheduling:availability"))
        page = self.client.get(reverse("scheduling:availability"))
        self.assertContains(page, "14 slots every week")

    def test_overlapping_session_shows_the_reason_on_the_page(self):
        """USAB-06: the page explains what went wrong."""
        self.log_in_as_doctor()
        self.add_monday_session()
        response = self.client.post(
            reverse("scheduling:rule_add"),
            {"weekday": 0, "start_time": "20:00", "end_time": "22:00", "slot_minutes": 15},
        )
        self.assertContains(response, "overlaps your Monday session")

    def test_doctor_cannot_change_another_doctors_schedule(self):
        """SEC-01: one doctor cannot delete another doctor's session."""
        other_rule = ScheduleRule.objects.create(
            doctor=self.other_doctor,
            weekday=1,
            start_time=time(9, 0),
            end_time=time(12, 0),
            slot_minutes=15,
        )
        self.log_in_as_doctor()
        response = self.client.post(reverse("scheduling:rule_delete", args=[other_rule.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ScheduleRule.objects.filter(pk=other_rule.pk).exists())

    def test_doctor_can_remove_their_own_session(self):
        """SCH-02: a doctor can remove a session they no longer work."""
        self.log_in_as_doctor()
        self.add_monday_session()
        rule = ScheduleRule.objects.get(doctor=self.doctor)
        self.client.post(reverse("scheduling:rule_delete", args=[rule.pk]))
        self.assertFalse(ScheduleRule.objects.filter(pk=rule.pk).exists())

    def test_doctor_without_a_profile_sees_an_explanation(self):
        """A doctor account with no profile is told what to do."""
        User.objects.create_user(
            username="newdoc", password="Strong-pass-123", role=User.Role.DOCTOR
        )
        self.client.login(username="newdoc", password="Strong-pass-123")
        page = self.client.get(reverse("scheduling:availability"))
        self.assertContains(page, "doctor profile has not been created")
