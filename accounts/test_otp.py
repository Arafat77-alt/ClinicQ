"""Tests for OTP rules (B4, AUTH-01/02, SEC-04)."""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from accounts.services.otp import (
    MAX_OTP_ATTEMPTS,
    OTP_BLOCK_MINUTES,
    OTP_EXPIRY_MINUTES,
    OTP_LENGTH,
    RESULT_EXPIRED,
    RESULT_OK,
    RESULT_TOO_MANY_ATTEMPTS,
    RESULT_WRONG_CODE,
    attempts_left,
    check_otp,
    generate_otp_code,
    get_result_message,
    is_attempt_limit_reached,
    is_blocked,
    is_otp_expired,
)


class GenerateOtpCodeTests(SimpleTestCase):
    def test_returns_six_digit_string(self):
        code = generate_otp_code()
        self.assertIsInstance(code, str)
        self.assertEqual(len(code), OTP_LENGTH)
        self.assertTrue(code.isdigit())

    def test_generates_different_codes_over_many_calls(self):
        codes = {generate_otp_code() for _ in range(50)}
        self.assertGreater(len(codes), 1)


class IsOtpExpiredTests(SimpleTestCase):
    def setUp(self):
        self.created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_not_expired_before_five_minutes(self):
        now = self.created_at + timedelta(minutes=4, seconds=59)
        self.assertFalse(is_otp_expired(self.created_at, now))

    def test_valid_at_exactly_five_minutes(self):
        now = self.created_at + timedelta(minutes=OTP_EXPIRY_MINUTES)
        self.assertFalse(is_otp_expired(self.created_at, now))

    def test_expired_after_five_minutes(self):
        now = self.created_at + timedelta(minutes=5, seconds=1)
        self.assertTrue(is_otp_expired(self.created_at, now))

    def test_expired_long_after(self):
        now = self.created_at + timedelta(minutes=30)
        self.assertTrue(is_otp_expired(self.created_at, now))


class AttemptLimitTests(SimpleTestCase):
    def test_not_reached_below_max(self):
        for used in range(MAX_OTP_ATTEMPTS):
            self.assertFalse(is_attempt_limit_reached(used))

    def test_reached_at_max(self):
        self.assertTrue(is_attempt_limit_reached(MAX_OTP_ATTEMPTS))

    def test_reached_above_max(self):
        self.assertTrue(is_attempt_limit_reached(MAX_OTP_ATTEMPTS + 1))

    def test_attempts_left_counts_down(self):
        self.assertEqual(attempts_left(0), 3)
        self.assertEqual(attempts_left(1), 2)
        self.assertEqual(attempts_left(2), 1)

    def test_attempts_left_never_below_zero(self):
        self.assertEqual(attempts_left(MAX_OTP_ATTEMPTS), 0)
        self.assertEqual(attempts_left(10), 0)


class IsBlockedTests(SimpleTestCase):
    def setUp(self):
        self.blocked_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_blocked_just_after(self):
        now = self.blocked_at + timedelta(seconds=1)
        self.assertTrue(is_blocked(self.blocked_at, now))

    def test_blocked_before_fifteen_minutes(self):
        now = self.blocked_at + timedelta(minutes=14, seconds=59)
        self.assertTrue(is_blocked(self.blocked_at, now))

    def test_not_blocked_at_exactly_fifteen_minutes(self):
        now = self.blocked_at + timedelta(minutes=OTP_BLOCK_MINUTES)
        self.assertFalse(is_blocked(self.blocked_at, now))

    def test_not_blocked_after_fifteen_minutes(self):
        now = self.blocked_at + timedelta(minutes=20)
        self.assertFalse(is_blocked(self.blocked_at, now))


class CheckOtpTests(SimpleTestCase):
    def setUp(self):
        self.created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.now = self.created_at + timedelta(minutes=1)
        self.code = "123456"

    def test_correct_code_returns_ok(self):
        result = check_otp(self.code, self.code, self.created_at, 0, self.now)
        self.assertEqual(result, RESULT_OK)

    def test_wrong_code_returns_wrong_code(self):
        result = check_otp("000000", self.code, self.created_at, 0, self.now)
        self.assertEqual(result, RESULT_WRONG_CODE)

    def test_expired_returns_expired(self):
        now = self.created_at + timedelta(minutes=6)
        result = check_otp(self.code, self.code, self.created_at, 0, now)
        self.assertEqual(result, RESULT_EXPIRED)

    def test_too_many_attempts_returns_too_many_attempts(self):
        result = check_otp(self.code, self.code, self.created_at, MAX_OTP_ATTEMPTS, self.now)
        self.assertEqual(result, RESULT_TOO_MANY_ATTEMPTS)

    def test_attempt_limit_checked_before_expiry_and_correctness(self):
        now = self.created_at + timedelta(minutes=10)
        result = check_otp(self.code, self.code, self.created_at, MAX_OTP_ATTEMPTS, now)
        self.assertEqual(result, RESULT_TOO_MANY_ATTEMPTS)

    def test_expiry_checked_before_code_correctness(self):
        now = self.created_at + timedelta(minutes=10)
        result = check_otp(self.code, self.code, self.created_at, 0, now)
        self.assertEqual(result, RESULT_EXPIRED)

    def test_strips_entered_code(self):
        result = check_otp(" 123456 ", self.code, self.created_at, 0, self.now)
        self.assertEqual(result, RESULT_OK)

    def test_empty_or_none_entered_is_wrong(self):
        self.assertEqual(check_otp("", self.code, self.created_at, 0, self.now), RESULT_WRONG_CODE)
        self.assertEqual(check_otp(None, self.code, self.created_at, 0, self.now), RESULT_WRONG_CODE)


class GetResultMessageTests(SimpleTestCase):
    def test_messages_for_known_results(self):
        self.assertIn("correct", get_result_message(RESULT_OK).lower())
        self.assertTrue(get_result_message(RESULT_WRONG_CODE))
        self.assertIn("expired", get_result_message(RESULT_EXPIRED).lower())
        self.assertIn("15", get_result_message(RESULT_TOO_MANY_ATTEMPTS))

    def test_unknown_result_raises(self):
        with self.assertRaises(ValueError):
            get_result_message("bogus")
