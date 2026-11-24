"""Tests for the administrator's doctor profile pages (SCH-01)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Patient, User
from booking.models import Appointment

from .models import Doctor


class DoctorProfilePageTests(TestCase):
    """SCH-01: clinic administrator adds, edits and deactivates doctor profiles."""

    def setUp(self):
        """Create an admin, a doctor account, a receptionist and a patient."""
        self.admin = User.objects.create_user(
            username="admin_farhan",
            email="farhan@example.com",
            password="Strong-pass-123",
            role=User.Role.ADMIN,
        )
        self.doctor_user = User.objects.create_user(
            username="dr_imran",
            email="imran@example.com",
            password="Strong-pass-123",
            role=User.Role.DOCTOR,
            first_name="Imran",
            last_name="Hossain",
        )
        self.receptionist = User.objects.create_user(
            username="shirin",
            email="shirin@example.com",
            password="Strong-pass-123",
            role=User.Role.RECEPTIONIST,
        )

    def test_only_administrator_can_open_doctor_profile_pages(self):
        """SEC-01 and SCH-01: non-admin roles are refused with status 403."""
        self.client.force_login(self.receptionist)
        response = self.client.get(reverse("scheduling:doctor_list"))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.doctor_user)
        response = self.client.get(reverse("scheduling:doctor_create"))
        self.assertEqual(response.status_code, 403)

    def test_admin_adds_doctor_and_doctor_appears_in_patient_search(self):
        """SCH-01 Confirmation 1: saved doctor appears in search with specialty and room."""
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("scheduling:doctor_create"),
            {
                "user": self.doctor_user.pk,
                "code": "D1",
                "specialty": "Cardiology",
                "room": "204",
                "default_slot_minutes": 15,
                "is_active": True,
            },
        )
        self.assertRedirects(response, reverse("scheduling:doctor_list"))
        self.assertTrue(Doctor.objects.filter(code="D1", specialty="Cardiology").exists())

        search_page = self.client.get(reverse("booking:doctor_search"), {"q": "Cardiology"})
        self.assertContains(search_page, "Imran Hossain")
        self.assertContains(search_page, "Cardiology")
        self.assertContains(search_page, "204")

    def test_duplicate_code_shows_a_plain_words_message(self):
        """USAB-06 and SCH-01: duplicate doctor code explains the problem and fix."""
        Doctor.objects.create(user=self.doctor_user, code="D2", specialty="General", room="101")
        other_doc_user = User.objects.create_user(
            username="dr_nadia",
            email="nadia@example.com",
            password="Strong-pass-123",
            role=User.Role.DOCTOR,
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("scheduling:doctor_create"),
            {
                "user": other_doc_user.pk,
                "code": "D2",
                "specialty": "Dermatology",
                "room": "102",
                "default_slot_minutes": 15,
                "is_active": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already used by another doctor")

    def test_deleting_doctor_with_future_appointments_offers_deactivate_instead(self):
        """SCH-01 Confirmation 2: delete offers to deactivate instead and removes from search."""
        doctor = Doctor.objects.create(
            user=self.doctor_user, code="D3", specialty="Neurology", room="301"
        )
        patient = Patient.objects.create(full_name="Rahima Akter", mobile_number="+8801712345678")
        start = (timezone.now() + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            slot_start=start,
            slot_end=start + timedelta(minutes=15),
        )

        self.client.force_login(self.admin)
        confirm_page = self.client.get(reverse("scheduling:doctor_delete", args=[doctor.pk]))
        self.assertContains(confirm_page, "Deactivate doctor instead")

        post_resp = self.client.post(reverse("scheduling:doctor_delete", args=[doctor.pk]))
        self.assertRedirects(post_resp, reverse("scheduling:doctor_list"))
        doctor.refresh_from_db()
        self.assertFalse(doctor.is_active)

        search_page = self.client.get(reverse("booking:doctor_search"), {"q": "Neurology"})
        self.assertNotContains(search_page, "Imran Hossain")
