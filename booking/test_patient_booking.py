"""Automated tests for patient online booking, listing, and cancellation.

Stories: BKG-03 (patient books a slot), BKG-04 (my appointments),
BKG-05 (patient cancels an appointment).
Requirements: BR-01 (one booking per slot), BR-03 (14-day window, 30-min lead),
BR-04 (2-hour cancellation lead time), REL-02 (no double booking),
SEC-01 / SEC-02 (patient role & family ownership checks).
"""

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from scheduling.models import Doctor, ScheduleRule

from .models import Appointment
from .patient_booking import (
    book_online_appointment,
    cancel_patient_appointment,
    list_patient_appointments,
)

DHAKA = ZoneInfo("Asia/Dhaka")
SUNDAY_MORNING = datetime(2026, 11, 15, 10, 0, tzinfo=DHAKA)
MONDAY_5PM = datetime(2026, 11, 16, 17, 0, tzinfo=DHAKA)
MONDAY_515PM = datetime(2026, 11, 16, 17, 15, tzinfo=DHAKA)


class PatientBookingTests(TestCase):
    """End-to-end and rule tests for BKG-03, BKG-04, and BKG-05."""

    def setUp(self):
        """Create a doctor with a Monday session, a patient, and a dependent."""
        doctor_user = User.objects.create_user(
            username="dr_sadia",
            password="Strong-pass-123",
            role=User.Role.DOCTOR,
            first_name="Sadia",
            last_name="Rahman",
        )
        self.doctor = Doctor.objects.create(
            user=doctor_user,
            code="SR01",
            specialty="Medicine",
            room="204",
        )
        ScheduleRule.objects.create(
            doctor=self.doctor,
            weekday=0,  # Monday
            start_time=time(17, 0),
            end_time=time(18, 0),
        )

        self.patient_user = User.objects.create_user(
            username="patient_8801711111111",
            role=User.Role.PATIENT,
        )
        self.patient_user.set_unusable_password()
        self.patient_user.save(update_fields=["password"])
        self.patient = Patient.objects.create(
            user=self.patient_user,
            full_name="Ayesha Siddiqua",
            mobile_number="+8801711111111",
        )
        self.dependent = Patient.objects.create(
            guardian=self.patient,
            full_name="Zayan Siddiqui",
            mobile_number="+8801711111111",
            approx_age=6,
        )

    def log_in_patient(self):
        """Attach the patient user to the test client session."""
        self.client.force_login(
            self.patient_user, backend="accounts.backends.EmailOrUsernameBackend"
        )

    def clock(self, fixed_now):
        """Pin ``django.utils.timezone.now`` to ``fixed_now`` inside a block."""
        return patch("django.utils.timezone.now", return_value=fixed_now)

    # --- BKG-03: Patient books a slot ---

    def test_anonymous_visitor_is_redirected_to_patient_login_when_booking(self):
        """BKG-03 + SEC-01: unauthenticated visitors cannot confirm a booking."""
        url = reverse("booking:book_slot", args=[self.doctor.pk])
        encoded_slot = MONDAY_5PM.isoformat().replace(":", "%3A").replace("+", "%2B")
        resp = self.client.get(f"{url}?slot={MONDAY_5PM.isoformat()}")
        self.assertRedirects(
            resp,
            f"{reverse('accounts:patient_login')}?next={url}%3Fslot%3D{encoded_slot}",
            fetch_redirect_response=False,
        )

    def test_patient_books_slot_for_self_and_sees_reference_number(self):
        """BKG-03: patient books a free slot and receives a CQ-XXXXXXXX reference."""
        self.log_in_patient()
        url = reverse("booking:book_slot", args=[self.doctor.pk])
        with self.clock(SUNDAY_MORNING):
            resp = self.client.post(
                url,
                {
                    "patient_id": self.patient.pk,
                    "slot_start": MONDAY_5PM.isoformat(),
                    "reason": "Persistent fever",
                },
            )
        appointment = Appointment.objects.get()
        self.assertRedirects(resp, reverse("booking:booking_confirmation", args=[appointment.pk]))
        self.assertEqual(appointment.type, Appointment.Type.ONLINE)
        self.assertEqual(appointment.status, Appointment.Status.BOOKED)
        self.assertEqual(appointment.patient, self.patient)
        self.assertTrue(appointment.reference_number.startswith("CQ-"))

        confirm_page = self.client.get(
            reverse("booking:booking_confirmation", args=[appointment.pk])
        )
        self.assertContains(confirm_page, appointment.reference_number)
        self.assertContains(confirm_page, "Ayesha Siddiqua")

    def test_patient_can_book_slot_for_dependent(self):
        """BKG-03 + AUTH-04: guardian can book an appointment for their dependent."""
        with self.clock(SUNDAY_MORNING):
            appointment = book_online_appointment(
                guardian_patient=self.patient,
                target_patient_id=self.dependent.pk,
                doctor=self.doctor,
                slot_start=MONDAY_5PM,
                booked_by=self.patient_user,
                reason="Childhood cough",
                now=SUNDAY_MORNING,
            )
        self.assertEqual(appointment.patient, self.dependent)

    def test_double_booking_same_slot_is_blocked(self):
        """BKG-03 + BR-01 + REL-02: second booking on the same slot fails cleanly."""
        book_online_appointment(
            guardian_patient=self.patient,
            target_patient_id=self.patient.pk,
            doctor=self.doctor,
            slot_start=MONDAY_5PM,
            booked_by=self.patient_user,
            now=SUNDAY_MORNING,
        )
        with self.assertRaises(ValidationError) as ctx:
            book_online_appointment(
                guardian_patient=self.patient,
                target_patient_id=self.dependent.pk,
                doctor=self.doctor,
                slot_start=MONDAY_5PM,
                booked_by=self.patient_user,
                now=SUNDAY_MORNING,
            )
        self.assertIn("no longer available", " ".join(ctx.exception.messages).lower())

    def test_cannot_book_for_unrelated_patient(self):
        """SEC-02: patient cannot book an appointment under another family's ID."""
        stranger = Patient.objects.create(
            full_name="Unrelated Person",
            mobile_number="+8801822222222",
        )
        with self.assertRaises(ValidationError):
            book_online_appointment(
                guardian_patient=self.patient,
                target_patient_id=stranger.pk,
                doctor=self.doctor,
                slot_start=MONDAY_5PM,
                booked_by=self.patient_user,
                now=SUNDAY_MORNING,
            )

    # --- BKG-04: My appointments ---

    def test_my_appointments_lists_upcoming_and_past_for_family(self):
        """BKG-04: patient sees upcoming and past appointments for self & dependents."""
        upcoming_appt = book_online_appointment(
            guardian_patient=self.patient,
            target_patient_id=self.dependent.pk,
            doctor=self.doctor,
            slot_start=MONDAY_5PM,
            booked_by=self.patient_user,
            now=SUNDAY_MORNING,
        )
        past_appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            slot_start=SUNDAY_MORNING - timedelta(days=7),
            slot_end=SUNDAY_MORNING - timedelta(days=7) + timedelta(minutes=15),
            type=Appointment.Type.ONLINE,
            status=Appointment.Status.COMPLETED,
        )

        upcoming, past = list_patient_appointments(self.patient, now=SUNDAY_MORNING)
        self.assertEqual([a.pk for a in upcoming], [upcoming_appt.pk])
        self.assertEqual([a.pk for a in past], [past_appt.pk])

        self.log_in_patient()
        with self.clock(SUNDAY_MORNING):
            page = self.client.get(reverse("booking:my_appointments"))
        self.assertContains(page, upcoming_appt.reference_number)
        self.assertContains(page, "Zayan Siddiqui")
        self.assertContains(page, past_appt.reference_number)

    # --- BKG-05: Patient cancels an appointment ---

    def test_patient_cancels_appointment_more_than_2_hours_ahead_and_frees_slot(self):
        """BKG-05 + BR-04: cancelling >= 2h ahead marks cancelled and frees the slot."""
        appt = book_online_appointment(
            guardian_patient=self.patient,
            target_patient_id=self.patient.pk,
            doctor=self.doctor,
            slot_start=MONDAY_5PM,
            booked_by=self.patient_user,
            now=SUNDAY_MORNING,
        )

        self.log_in_patient()
        # Cancel at 14:30 Monday (2.5 hours before 17:00) -> allowed.
        with self.clock(MONDAY_5PM - timedelta(hours=2, minutes=30)):
            resp = self.client.post(reverse("booking:cancel_appointment", args=[appt.pk]))
        self.assertRedirects(resp, reverse("booking:my_appointments"))

        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)

        # Slot is immediately available to book again.
        rebooked = book_online_appointment(
            guardian_patient=self.patient,
            target_patient_id=self.dependent.pk,
            doctor=self.doctor,
            slot_start=MONDAY_5PM,
            booked_by=self.patient_user,
            now=MONDAY_5PM - timedelta(hours=2),
        )
        self.assertEqual(rebooked.status, Appointment.Status.BOOKED)

    def test_patient_cannot_cancel_within_2_hours_of_appointment(self):
        """BKG-05 + BR-04: cancellation is blocked less than 2 hours before start."""
        appt = book_online_appointment(
            guardian_patient=self.patient,
            target_patient_id=self.patient.pk,
            doctor=self.doctor,
            slot_start=MONDAY_5PM,
            booked_by=self.patient_user,
            now=SUNDAY_MORNING,
        )

        # 1 hour 59 minutes before 17:00 -> refused.
        with self.assertRaises(ValidationError) as ctx:
            cancel_patient_appointment(
                self.patient,
                appt.pk,
                now=MONDAY_5PM - timedelta(hours=1, minutes=59),
            )
        self.assertIn("2 hours", " ".join(ctx.exception.messages))
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.BOOKED)

    def test_patient_cannot_cancel_stranger_appointment_sec01(self):
        """BKG-05 + SEC-02: patient cannot cancel an appointment outside their family."""
        stranger = Patient.objects.create(
            full_name="Other Patient",
            mobile_number="+8801833333333",
        )
        stranger_appt = Appointment.objects.create(
            patient=stranger,
            doctor=self.doctor,
            slot_start=MONDAY_515PM,
            slot_end=MONDAY_515PM + timedelta(minutes=15),
            type=Appointment.Type.ONLINE,
            status=Appointment.Status.BOOKED,
        )
        with self.assertRaises(ValidationError):
            cancel_patient_appointment(self.patient, stranger_appt.pk, now=SUNDAY_MORNING)

    def test_patient_cannot_cancel_another_patients_appointment(self):
        """BKG-05 + SEC-01: patient cannot cancel an appointment outside their family."""
        stranger = Patient.objects.create(
            full_name="Other Patient",
            mobile_number="+8801833333333",
        )
        stranger_appt = Appointment.objects.create(
            patient=stranger,
            doctor=self.doctor,
            slot_start=MONDAY_515PM,
            slot_end=MONDAY_515PM + timedelta(minutes=15),
            type=Appointment.Type.ONLINE,
            status=Appointment.Status.BOOKED,
        )
        with self.assertRaises(ValidationError):
            cancel_patient_appointment(self.patient, stranger_appt.pk, now=SUNDAY_MORNING)

    def test_patient_can_cancel_needs_rescheduling_even_within_2_hours(self):
        """BKG-05: clinic-triggered needs_rescheduling can be cancelled < 2h before start."""
        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            slot_start=MONDAY_5PM,
            slot_end=MONDAY_515PM,
            type=Appointment.Type.ONLINE,
            status=Appointment.Status.NEEDS_RESCHEDULING,
        )
        cancelled = cancel_patient_appointment(
            self.patient,
            appt.pk,
            now=MONDAY_5PM - timedelta(minutes=30),
        )
        self.assertEqual(cancelled.status, Appointment.Status.CANCELLED)
