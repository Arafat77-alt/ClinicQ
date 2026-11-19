"""Tests for the phone-friendly shared page layout (SYS-02, COMP-02)."""

from django.test import TestCase
from django.urls import reverse


class PhoneFriendlyLayoutTests(TestCase):
    """SYS-02 and COMP-02: 360px phone layout, 44x44px buttons and scrollable tables."""

    def test_base_template_has_viewport_and_44px_button_targets(self):
        """Every page using base.html includes viewport meta and 44px minimum button size."""
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="viewport"')
        self.assertContains(response, "min-height: 44px")
        self.assertContains(response, "min-width: 44px")
        self.assertContains(response, "overflow-x: auto")
