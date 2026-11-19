"""Unit tests for the waiting-time calculation (QUE-04, QUE-13, BR-12)."""

import unittest

from queueing.estimate import (
    average_consultation_minutes,
    estimate_waiting_range,
    format_waiting_estimate,
)


class WaitingTimeEstimateTests(unittest.TestCase):
    """QUE-04 and BR-12: waiting-time range from patients ahead and doctor average."""

    def test_three_patients_ahead_with_twelve_minute_average_gives_30_to_45(self):
        """Three patients ahead with a 12-min average is 36 min; 28.8..43.2 rounds to 30..45."""
        durations = [12, 12, 12, 12, 12]
        low, high = estimate_waiting_range(
            patients_ahead=3,
            completed_durations=durations,
            minutes_with_current_patient=0,
        )
        self.assertEqual((low, high), (30, 45))
        self.assertEqual(
            format_waiting_estimate(3, completed_durations=durations),
            "about 30–45 min",
        )

    def test_time_already_spent_with_current_patient_lowers_the_estimate(self):
        """BR-12: time already spent in the active consultation reduces the wait."""
        durations = [12, 12, 12, 12, 12]
        # 3 * 12 - 11 = 25 minutes -> 20% range is 20 to 30 minutes
        low, high = estimate_waiting_range(
            patients_ahead=3,
            completed_durations=durations,
            minutes_with_current_patient=11,
        )
        self.assertEqual((low, high), (20, 30))

    def test_estimate_is_never_below_zero(self):
        """BR-12: even if the current consultation runs overtime, the wait is never negative."""
        durations = [10, 10, 10, 10, 10]
        low, high = estimate_waiting_range(
            patients_ahead=1,
            completed_durations=durations,
            minutes_with_current_patient=25,
        )
        self.assertEqual((low, high), (0, 0))
        self.assertEqual(estimate_waiting_range(patients_ahead=0), (0, 0))

    def test_fewer_than_five_completed_consultations_uses_the_slot_length(self):
        """BR-12: when fewer than 5 completed visits exist, use the doctor's slot length."""
        self.assertEqual(
            average_consultation_minutes([8, 9, 10, 11], default_slot_minutes=15),
            15.0,
        )
        # 2 patients ahead * 15 min default slot = 30 min -> 24..36 -> rounds to 25..35
        low, high = estimate_waiting_range(
            patients_ahead=2,
            completed_durations=[10, 10, 10],
            default_slot_minutes=15,
        )
        self.assertEqual((low, high), (25, 35))

    def test_only_the_last_twenty_consultations_are_counted(self):
        """BR-12: older visits beyond the last 20 do not skew the average."""
        old_slow_visits = [30] * 10
        recent_twenty_visits = [10] * 20
        avg = average_consultation_minutes(old_slow_visits + recent_twenty_visits)
        self.assertEqual(avg, 10.0)


if __name__ == "__main__":
    unittest.main()
