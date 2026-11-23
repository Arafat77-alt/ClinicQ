"""Tests for the notifications application."""

from contextlib import redirect_stdout
from io import StringIO

from django.test import SimpleTestCase

from .services import send_email, send_sms


class SendSmsTests(SimpleTestCase):
    """NOT-01: confirmation messages."""

    def test_message_is_printed_and_true_is_returned(self):
        """The message reaches the terminal and the caller is told it worked."""
        output = StringIO()
        with redirect_stdout(output):
            result = send_sms("+8801712345678", "Your appointment is confirmed.")
        self.assertTrue(result)
        self.assertIn("+8801712345678", output.getvalue())
        self.assertIn("Your appointment is confirmed.", output.getvalue())

    def test_empty_number_gives_a_clear_message(self):
        """USAB-06: say why it failed and what to do."""
        with self.assertRaises(ValueError) as caught:
            send_sms("", "Hello")
        self.assertIn("No mobile number was given", str(caught.exception))


class SendEmailTests(SimpleTestCase):
    """NOT-01: confirmation emails."""

    def test_email_is_printed_and_true_is_returned(self):
        """The email reaches the terminal and the caller is told it worked."""
        output = StringIO()
        with redirect_stdout(output):
            result = send_email("rahima@example.com", "Appointment", "See you on Monday.")
        self.assertTrue(result)
        self.assertIn("rahima@example.com", output.getvalue())

    def test_empty_address_gives_a_clear_message(self):
        """USAB-06: say why it failed and what to do."""
        with self.assertRaises(ValueError) as caught:
            send_email("", "Appointment", "Hello")
        self.assertIn("No email address was given", str(caught.exception))
