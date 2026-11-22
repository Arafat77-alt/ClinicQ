"""Tests for the patient live queue status page and polling endpoint (QUE-04, PRIV-05)."""

from django.urls import reverse

from accounts.models import User

from .models import QueueEntry
from .services import add_to_queue
from .tests import QueueTestCase, at


class LiveQueueViewTests(QueueTestCase):
    """QUE-04 part 2: patient sees token, live position and estimate range."""

    def setUp(self):
        """Create three checked-in patients in one doctor's queue."""
        super().setUp()
        self.first_entry = add_to_queue(self.make_appointment(start=at(17, 0)), at(16, 50))
        self.second_entry = add_to_queue(self.make_appointment(start=at(17, 15)), at(17, 0))
        self.third_entry = add_to_queue(self.make_appointment(start=at(17, 30)), at(17, 10))

        self.patient_user = User.objects.create_user(
            username="patient_three",
            password="Strong-pass-123",
            role=User.Role.PATIENT,
        )
        third_patient = self.third_entry.appointment.patient
        third_patient.user = self.patient_user
        third_patient.save(update_fields=["user"])

        self.other_user = User.objects.create_user(
            username="patient_other",
            password="Strong-pass-123",
            role=User.Role.PATIENT,
        )
        first_patient = self.first_entry.appointment.patient
        first_patient.user = self.other_user
        first_patient.save(update_fields=["user"])

    def test_checked_in_third_patient_sees_token_position_and_range_estimate(self):
        """QUE-04 Confirmations 1 & 2: shows token, 3rd position and range (not exact time)."""
        self.client.force_login(self.patient_user)
        url = reverse("queueing:live_status", args=[self.third_entry.appointment_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.third_entry.token)
        self.assertContains(response, "#3")
        self.assertContains(response, "about")

        json_url = reverse("queueing:live_status_json", args=[self.third_entry.appointment_id])
        json_response = self.client.get(json_url)
        self.assertEqual(json_response.status_code, 200)
        payload = json_response.json()
        self.assertEqual(payload["token"], self.third_entry.token)
        self.assertEqual(payload["position"], 3)
        self.assertEqual(payload["patients_ahead"], 2)
        self.assertIn("about", payload["estimate_text"])

    def test_position_updates_to_second_when_patient_ahead_is_called(self):
        """QUE-04 Confirmation 1: calling someone ahead moves 3rd patient to 2nd."""
        self.first_entry.state = QueueEntry.State.CALLED
        self.first_entry.called_at = at(17, 15)
        self.first_entry.save(update_fields=["state", "called_at"])

        self.client.force_login(self.patient_user)
        json_url = reverse("queueing:live_status_json", args=[self.third_entry.appointment_id])
        payload = self.client.get(json_url).json()

        self.assertEqual(payload["position"], 2)
        self.assertEqual(payload["patients_ahead"], 1)

    def test_another_patient_cannot_view_someone_elses_live_status(self):
        """PRIV-05 and SEC-01: another patient gets 403 on HTML and JSON endpoints."""
        self.client.force_login(self.other_user)
        html_url = reverse("queueing:live_status", args=[self.third_entry.appointment_id])
        json_url = reverse("queueing:live_status_json", args=[self.third_entry.appointment_id])

        self.assertEqual(self.client.get(html_url).status_code, 403)
        self.assertEqual(self.client.get(json_url).status_code, 403)

    def test_anonymous_visitor_is_redirected_to_patient_login(self):
        """AUTH-02: unauthenticated visitors are redirected to patient login."""
        html_url = reverse("queueing:live_status", args=[self.third_entry.appointment_id])
        response = self.client.get(html_url)
        self.assertRedirects(
            response,
            f"{reverse('accounts:patient_login')}?next={html_url}",
            fetch_redirect_response=False,
        )
