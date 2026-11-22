"""Unit tests for completing a consultation or skipping a patient (QUE-08, BR-10)."""

from django.core.exceptions import ValidationError

from booking.models import Appointment

from .completion import complete_consultation, consultation_duration_minutes, skip_patient
from .models import QueueEntry
from .services import add_to_queue, waiting_queue
from .tests import MONDAY, QueueTestCase, at


class CompletionAndSkipTests(QueueTestCase):
    """QUE-08 and BR-10: finishing consultations and enforcing the 2-skip limit."""

    def test_completing_records_duration_and_updates_entry_and_appointment(self):
        """QUE-08 Confirmation 1: Complete sets both states to Completed and stores duration."""
        appointment = self.make_appointment(start=at(17, 0))
        entry = add_to_queue(appointment, at(16, 55))
        entry.state = QueueEntry.State.IN_CONSULTATION
        entry.called_at = at(17, 0)
        entry.started_at = at(17, 2)
        entry.save()

        duration = complete_consultation(entry, now=at(17, 16))
        entry.refresh_from_db()
        appointment.refresh_from_db()

        self.assertEqual(entry.state, QueueEntry.State.COMPLETED)
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)
        self.assertEqual(entry.completed_at, at(17, 16))
        self.assertEqual(duration, 14.0)
        self.assertEqual(consultation_duration_minutes(entry), 14.0)

    def test_first_skip_puts_patient_behind_all_current_waiters(self):
        """QUE-08 Confirmation 2 & BR-10: 1st skip returns patient to Waiting with effective=now."""
        first = add_to_queue(self.make_appointment(start=at(17, 0)), at(16, 50))
        second = add_to_queue(self.make_appointment(start=at(17, 15)), at(17, 5))
        third = add_to_queue(self.make_appointment(start=at(17, 30)), at(17, 10))

        first.state = QueueEntry.State.CALLED
        first.called_at = at(17, 35)
        first.save()

        skip_patient(first, now=at(17, 40))
        first.refresh_from_db()

        self.assertEqual(first.state, QueueEntry.State.WAITING)
        self.assertEqual(first.skip_count, 1)
        self.assertEqual(first.effective_time, at(17, 40))
        self.assertEqual(waiting_queue(self.doctor, MONDAY), [second, third, first])

    def test_second_skip_sends_patient_to_reception_to_decide(self):
        """QUE-08 Confirmation 2 & BR-10: 2nd skip moves patient to Reception to decide."""
        entry = add_to_queue(self.make_appointment(start=at(17, 0)), at(16, 55))

        # 1st call and skip
        entry.state = QueueEntry.State.CALLED
        entry.save()
        skip_patient(entry, now=at(17, 10))

        # 2nd call and skip
        entry.state = QueueEntry.State.CALLED
        entry.save()
        skip_patient(entry, now=at(17, 25))
        entry.refresh_from_db()

        self.assertEqual(entry.skip_count, 2)
        self.assertEqual(entry.state, QueueEntry.State.RECEPTION_TO_DECIDE)
        self.assertNotIn(entry, waiting_queue(self.doctor, MONDAY))

    def test_third_skip_is_refused_with_a_plain_words_message(self):
        """BR-10 and USAB-06: after 2 skips a doctor cannot skip the patient again."""
        entry = self.make_entry(1, state=QueueEntry.State.RECEPTION_TO_DECIDE, skip_count=2)
        with self.assertRaises(ValidationError) as caught:
            skip_patient(entry, now=at(17, 40))
        self.assertIn("already been skipped 2 times", str(caught.exception))

    def test_cannot_complete_or_skip_a_waiting_patient(self):
        """USAB-06: plain-language refusal when trying to complete/skip someone not called."""
        entry = add_to_queue(self.make_appointment(start=at(17, 0)), at(16, 55))
        with self.assertRaises(ValidationError) as caught_complete:
            complete_consultation(entry, now=at(17, 10))
        self.assertIn("Call the patient first", str(caught_complete.exception))

        with self.assertRaises(ValidationError) as caught_skip:
            skip_patient(entry, now=at(17, 10))
        self.assertIn("Call the patient first", str(caught_skip.exception))
