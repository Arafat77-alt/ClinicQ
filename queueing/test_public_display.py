"""Tests for the public waiting-room display (QUE-11, PRIV-03, PERF-03)."""

import json
from unittest.mock import patch

from django.urls import reverse

from .display import public_display_snapshot
from .models import QueueEntry
from .tests import QueueTestCase, at


class PublicDisplaySnapshotTests(QueueTestCase):
    """QUE-11: per-doctor tokens without any patient information (PRIV-03)."""

    def setUp(self):
        """Create a called patient and one waiting patient for each doctor."""
        super().setUp()
        self.current = self.make_entry(1, state=QueueEntry.State.IN_CONSULTATION)
        self.waiting = self.make_entry(2)
        self.other = self.make_entry(3, doctor=self.other_doctor)
        self.current.appointment.patient.full_name = "Secret Patient Name"
        self.current.appointment.patient.save(update_fields=["full_name"])
        self.current.appointment.reason = "Cholera"
        self.current.appointment.save(update_fields=["reason"])

    def test_snapshot_shows_doctor_code_room_token_and_waiting_count(self):
        """Criterion: the screen shows doctor, token, room and a waiting count."""
        snapshot = public_display_snapshot(now=at(17, 6))
        rows = {row["code"]: row for row in snapshot["doctors"]}
        self.assertEqual(rows["D2"]["room"], "101")
        self.assertEqual(rows["D2"]["current"]["token"], self.current.token)
        self.assertEqual(rows["D2"]["current"]["state_display"], "In consultation")
        self.assertEqual(rows["D2"]["waiting_count"], 1)
        self.assertEqual(rows["D2"]["next_tokens"], [self.waiting.token])
        self.assertIsNone(rows["D3"]["current"])
        self.assertEqual(rows["D3"]["waiting_count"], 1)
        self.assertEqual(snapshot["updated_at"], "17:06:00")

    def test_snapshot_never_contains_names_reasons_or_phone_numbers(self):
        """PRIV-03: neither the page nor the poll exposes medical or personal data."""
        snapshot = json.dumps(public_display_snapshot(now=at(17, 6)))
        self.assertNotIn("Secret Patient Name", snapshot)
        self.assertNotIn("Cholera", snapshot)
        self.assertNotIn("+88017", snapshot)

    def test_new_call_replaces_the_current_token(self):
        """PERF-03: the next poll reflects a doctor calling the next patient."""
        QueueEntry.objects.filter(pk=self.current.pk).update(state=QueueEntry.State.COMPLETED)
        QueueEntry.objects.filter(pk=self.waiting.pk).update(state=QueueEntry.State.CALLED)
        rows = {row["code"]: row for row in public_display_snapshot(now=at(17, 7))["doctors"]}
        self.assertEqual(rows["D2"]["current"]["token"], self.waiting.token)
        self.assertEqual(rows["D2"]["waiting_count"], 0)


class PublicDisplayPageTests(QueueTestCase):
    """QUE-11: a visitor needs no account to open the screen or its data URL."""

    def setUp(self):
        """Resolve the URLs and freeze the clinic day used by the screen."""
        super().setUp()
        clock = patch("queueing.display.timezone.now", return_value=at(17, 6))
        clock.start()
        self.addCleanup(clock.stop)
        self.page_url = reverse("queueing:public_display")
        self.data_url = reverse("queueing:public_display_data")

    def test_anonymous_visitor_sees_tokens_but_no_patient_details(self):
        """Criterion: the waiting-room screen is readable without logging in."""
        entry = self.make_entry(1, state=QueueEntry.State.IN_CONSULTATION)
        entry.appointment.patient.full_name = "Hidden Patient"
        entry.appointment.patient.save(update_fields=["full_name"])
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Now serving")
        self.assertContains(response, entry.token)
        self.assertContains(response, "Room 101")
        self.assertNotContains(response, "Hidden Patient")
        self.assertContains(response, "setInterval(refreshDisplay, 3000)")

    def test_anonymous_json_poll_returns_the_same_safe_snapshot(self):
        """PERF-03: the three-second poll is public and refresh-stamped."""
        self.make_entry(1, state=QueueEntry.State.CALLED)
        data = self.client.get(self.data_url).json()
        self.assertEqual(data["doctors"][0]["current"]["token"], "D2-001")
        self.assertIn("updated_at", data)
        self.assertNotIn("patient_name", json.dumps(data))
