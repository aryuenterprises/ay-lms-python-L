from unittest.mock import MagicMock, patch
import requests
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from resources.models import Resources
from resources.views import ResourcesViewSet
from lead.models import Lead


@override_settings(
    CLOUDFLARE_TURNSTILE_SECRET_KEY="test-secret-key",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ResourcesTurnstileTestCase(TestCase):
    """
    Tests for Cloudflare Turnstile CAPTCHA in Resources download/submission API.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ResourcesViewSet.as_view({"post": "download"})
        self.resource = Resources.objects.create(
            title="Django Blueprint",
            slug="django-blueprint",
            status="active",
            form=True,
        )

    @patch("resources.views.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_success_submission_succeeds(self, mock_cf_post, mock_telecrm_post):
        # 1. captcha_token supplied + Cloudflare success -> resource submission succeeds
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Resource Captcha User",
                "phone": "9876543201",
                "email": "res_cf@example.com",
                "city": "Bangalore",
                "captcha_token": "valid-turnstile-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        self.assertIn("Downloaded:", response.data.get("message", ""))
        mock_cf_post.assert_called_once()
        self.assertTrue(Lead.objects.filter(phone="9876543201").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_invalid_captcha_submission_rejected(self, mock_cf_post):
        # 2. captcha_token supplied + invalid CAPTCHA -> submission rejected
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error-codes": ["invalid-input-response"],
        }
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Invalid User",
                "phone": "9876543202",
                "email": "invalid@example.com",
                "captcha_token": "invalid-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("verification failed", response.data.get("message", "").lower())
        self.assertFalse(Lead.objects.filter(phone="9876543202").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_expired_invalid_token_submission_rejected(self, mock_cf_post):
        # 3. captcha_token supplied + expired/invalid token -> submission rejected
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error-codes": ["timeout-or-duplicate"],
        }
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Expired User",
                "phone": "9876543203",
                "captcha_token": "expired-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertFalse(Lead.objects.filter(phone="9876543203").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_timeout_submission_rejected(self, mock_cf_post):
        # 4. captcha_token supplied + Cloudflare timeout -> submission rejected
        mock_cf_post.side_effect = requests.Timeout("Timed out")

        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Timeout User",
                "phone": "9876543204",
                "captcha_token": "timeout-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("unavailable", response.data.get("message", "").lower())
        self.assertFalse(Lead.objects.filter(phone="9876543204").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_network_error_submission_rejected(self, mock_cf_post):
        # 5. captcha_token supplied + Cloudflare/network error -> submission rejected
        mock_cf_post.side_effect = requests.ConnectionError("Connection failed")

        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Net Error User",
                "phone": "9876543205",
                "captcha_token": "conn-error-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("unavailable", response.data.get("message", "").lower())
        self.assertFalse(Lead.objects.filter(phone="9876543205").exists())

    @patch("resources.views.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_no_captcha_token_existing_resource_submission_unchanged(self, mock_cf_post, mock_telecrm_post):
        # 6. No captcha_token -> existing resource submission behavior remains unchanged
        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "No Captcha User",
                "phone": "9876543206",
                "email": "nocaptcha@example.com",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        mock_cf_post.assert_not_called()
        self.assertTrue(Lead.objects.filter(phone="9876543206").exists())

    @patch("resources.views.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_captcha_token_is_not_persisted_in_lead(self, mock_cf_post, mock_telecrm_post):
        # 7. CAPTCHA token is not persisted
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Persist Check User",
                "phone": "9876543207",
                "captcha_token": "token-not-to-save",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.get(phone="9876543207")
        self.assertFalse(hasattr(lead, "captcha_token"))

    @patch("resources.views.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_captcha_token_is_not_returned_in_api_response(self, mock_cf_post, mock_telecrm_post):
        # 8. CAPTCHA token is not returned in API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Response Check User",
                "phone": "9876543208",
                "captcha_token": "secret-turnstile-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("captcha_token", response.data)
        self.assertNotIn("turnstile_token", response.data)

    @patch("requests.post")
    def test_existing_lead_validation_still_works_with_valid_captcha(self, mock_cf_post):
        # 9. Existing validation still works (phone invalid length)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        # Phone with < 7 digits is rejected per LeadCaptureSerializer.validate_phone
        request = self.factory.post(
            f"/resources/{self.resource.slug}/download/",
            data={
                "name": "Invalid Phone User",
                "phone": "123",
                "captcha_token": "valid-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.resource.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(response.data.get("message"), "Validation failed")
        self.assertFalse(Lead.objects.filter(name="Invalid Phone User").exists())
