"""
lead/tests.py

Comprehensive tests for TeleCRM integration across all Lead operations.
Covers payload building, serializer creation/updates, ViewSet CRUD/bulk operations,
call logging, webinar registrations, resource downloads, social logins, WhatsApp chat,
error resilience, and transaction safety.
"""

from unittest.mock import MagicMock, patch
import requests
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from aryuapp.models import User
from lead.models import Lead, LeadCallLog
from lead.serializers import LeadSerializer, PublicLeadCreateSerializer
from lead.telecrm import (
    TeleCRMService,
    build_telecrm_payload,
    format_telecrm_phone,
    sync_lead_to_telecrm,
)
from lead.views import LeadViewSet, PublicLeadViewSet


class TeleCRMPayloadAndServiceTestCase(TestCase):
    """
    Tests for format_telecrm_phone, build_telecrm_payload, and TeleCRMService.
    """

    def setUp(self):
        self.user = User.objects.create(
            username="advisor_jane",
            full_name="Jane Doe",
            email="jane@example.com",
        )
        self.lead = Lead.objects.create(
            name="John Smith",
            phone="9876543210",
            email="john@example.com",
            city="Chennai",
            state="Tamil Nadu",
            course="Python Fullstack",
            status="fresh",
            priority="high",
            source="website",
            followup_by=self.user,
        )

    def test_format_telecrm_phone(self):
        self.assertEqual(format_telecrm_phone("9876543210"), "919876543210")
        self.assertEqual(format_telecrm_phone("+919876543210"), "919876543210")
        self.assertEqual(format_telecrm_phone("919876543210"), "919876543210")
        self.assertEqual(format_telecrm_phone(""), "")
        self.assertEqual(format_telecrm_phone(None), "")

    def test_build_telecrm_payload_from_lead_model(self):
        payload = build_telecrm_payload(
            self.lead,
            action_type="ACTION_1001",
            action_note="Test Lead Note",
        )
        fields = payload.get("fields", {})
        self.assertEqual(fields.get("name"), "John Smith")
        self.assertEqual(fields.get("phone"), "919876543210")
        self.assertEqual(fields.get("email"), "john@example.com")
        self.assertEqual(fields.get("city"), "Chennai")
        self.assertEqual(fields.get("state"), "Tamil Nadu")
        self.assertEqual(fields.get("course"), "Python Fullstack")
        self.assertEqual(fields.get("status"), "fresh")
        self.assertEqual(fields.get("priority"), "high")
        self.assertEqual(fields.get("source"), "website")
        self.assertEqual(fields.get("assigned_to"), "Jane Doe")

        actions = payload.get("actions", [])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "ACTION_1001")
        self.assertEqual(actions[0]["fields"]["note"], "Test Lead Note")

    def test_build_telecrm_payload_from_dict(self):
        lead_dict = {
            "name": "Alice Bob",
            "phone": "9123456789",
            "email": "alice@example.com",
            "course": "Java",
            "status": "pending",
        }
        payload = build_telecrm_payload(lead_dict, action_note="Dict Note")
        fields = payload.get("fields", {})
        self.assertEqual(fields.get("name"), "Alice Bob")
        self.assertEqual(fields.get("phone"), "919123456789")
        self.assertEqual(fields.get("email"), "alice@example.com")
        self.assertEqual(fields.get("course"), "Java")
        self.assertEqual(fields.get("status"), "pending")

    @patch("requests.post")
    def test_telecrm_service_send_payload_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "message": "Lead updated"}
        mock_post.return_value = mock_response

        payload = {"fields": {"name": "Test", "phone": "919876543210"}}
        result = TeleCRMService.send_payload(payload)

        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["data"]["status"], "success")
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_telecrm_service_send_payload_http_error_handled_gracefully(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal Server Error"}
        mock_post.return_value = mock_response

        payload = {"fields": {"name": "Test", "phone": "919876543210"}}
        result = TeleCRMService.send_payload(payload)

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 500)

    @patch("requests.post")
    def test_telecrm_service_timeout_handled_gracefully(self, mock_post):
        mock_post.side_effect = requests.Timeout("Connection timed out")

        payload = {"fields": {"name": "Test", "phone": "919876543210"}}
        result = TeleCRMService.send_payload(payload)

        self.assertFalse(result["success"])
        self.assertIn("Timeout", result["error"])


class LeadSerializersTeleCRMSyncTestCase(TestCase):
    """
    Tests verifying that LeadSerializer and PublicLeadCreateSerializer
    consistently trigger TeleCRM sync on creation and updates.
    """

    @patch("lead.serializers.sync_lead_to_telecrm")
    def test_lead_serializer_create_triggers_telecrm(self, mock_sync):
        data = {
            "name": "Serializer Lead",
            "phone": "9876543211",
            "email": "serializer@example.com",
            "course": "DevOps",
            "status": "fresh",
        }
        serializer = LeadSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        lead = serializer.save()

        mock_sync.assert_called_once_with(lead, action_note="Lead Created")
        self.assertEqual(lead.name, "Serializer Lead")

    @patch("lead.serializers.sync_lead_to_telecrm")
    def test_lead_serializer_update_triggers_telecrm(self, mock_sync):
        lead = Lead.objects.create(
            name="Original Name",
            phone="9876543212",
            status="fresh",
        )
        data = {
            "status": "interested",
            "course": "Data Science",
        }
        serializer = LeadSerializer(lead, data=data, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated_lead = serializer.save()

        mock_sync.assert_called_once_with(
            updated_lead,
            action_note="Lead Updated: Status=interested",
        )
        self.assertEqual(updated_lead.status, "interested")

    @patch("lead.serializers.sync_lead_to_telecrm")
    def test_public_lead_create_serializer_triggers_telecrm(self, mock_sync):
        data = {
            "name": "Public Lead",
            "phone": "9876543213",
            "email": "public@example.com",
            "course": "Cybersecurity",
            "source": "meta_ads",
        }
        serializer = PublicLeadCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        lead = serializer.save()

        mock_sync.assert_called_once_with(lead, action_note="Lead Created From Website")
        self.assertEqual(lead.source, "meta_ads")
        self.assertEqual(lead.created_by_type, "public")


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class LeadViewSetTeleCRMSyncTestCase(TestCase):
    """
    Tests verifying that LeadViewSet CRUD, bulk upload, delete/archive,
    and call logging operations trigger TeleCRM synchronization.
    """

    def setUp(self):
        self.admin = User.objects.create(
            username="admin_user",
            is_staff=True,
            is_superuser=True,
            full_name="Admin Boss",
        )
        self.factory = APIRequestFactory()

    @patch("lead.views.sync_lead_to_telecrm")
    def test_viewset_destroy_triggers_telecrm_archive(self, mock_sync):
        lead = Lead.objects.create(
            name="To Archive",
            phone="9876543214",
            status="fresh",
        )
        request = self.factory.delete(f"/lead-engine/leads/{lead.id}/")
        force_authenticate(request, user=self.admin)

        view = LeadViewSet.as_view({"delete": "destroy"})
        response = view(request, pk=lead.id)
        self.assertEqual(response.status_code, 200)

        lead.refresh_from_db()
        self.assertTrue(lead.is_archived)
        mock_sync.assert_called_once_with(lead, action_note="Lead Archived")

    @patch("lead.views.sync_lead_to_telecrm")
    def test_viewset_add_call_log_triggers_telecrm(self, mock_sync):
        lead = Lead.objects.create(
            name="Call Target",
            phone="9876543215",
            status="fresh",
        )
        request = self.factory.post(
            f"/lead/{lead.id}/add_call_log/",
            data={
                "duration_seconds": 120,
                "call_status": "Interested",
                "remarks": "Wants Python brochure",
            },
            format="multipart",
        )
        force_authenticate(request, user=self.admin)

        view = LeadViewSet.as_view({"post": "add_call_log"})
        response = view(request, pk=lead.id)
        self.assertEqual(response.status_code, 201)

        self.assertEqual(LeadCallLog.objects.filter(lead=lead).count(), 1)
        mock_sync.assert_called_once()
        args, kwargs = mock_sync.call_args
        self.assertEqual(args[0], lead)
        self.assertIn("Call Log Added: Interested - Wants Python brochure", kwargs.get("action_note", ""))

    @patch("lead.views.sync_leads_bulk_to_telecrm")
    def test_viewset_bulk_upload_triggers_telecrm_bulk_sync(self, mock_bulk_sync):
        csv_content = (
            b"name,phone,email,city,course\n"
            b"Bulk User 1,9876543221,user1@example.com,Chennai,Python\n"
            b"Bulk User 2,9876543222,user2@example.com,Bangalore,Java\n"
        )
        from django.core.files.uploadedfile import SimpleUploadedFile

        file_obj = SimpleUploadedFile("leads.csv", csv_content, content_type="text/csv")
        request = self.factory.post(
            "/lead/bulk-upload/",
            data={"file": file_obj},
            format="multipart",
        )
        force_authenticate(request, user=self.admin)

        view = LeadViewSet.as_view({"post": "bulk_upload"})
        response = view(request)
        self.assertEqual(response.status_code, 201)

        mock_bulk_sync.assert_called_once()
        args, kwargs = mock_bulk_sync.call_args
        bulk_leads = args[0]
        self.assertEqual(len(bulk_leads), 2)
        self.assertEqual(kwargs.get("action_note"), "Bulk Lead Upload")


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class CrossModuleTeleCRMSyncTestCase(TestCase):
    """
    Tests verifying TeleCRM integration in cross-module contexts:
    Webinar registration, Resource download, Social auth login.
    """

    @patch("webinar.serializers.sync_lead_to_telecrm")
    def test_webinar_registration_triggers_telecrm(self, mock_sync):
        from django.utils import timezone
        from webinar.models import Webinar
        from webinar.serializers import WebinarRegistrationSerializer

        webinar = Webinar.objects.create(
            title="Mastering Django",
            slug="mastering-django",
            description="Complete Django guide",
            mentor="Dr. Django",
            scheduled_start=timezone.now(),
            created_by="admin",
            created_by_type="admin",
        )
        data = {
            "name": "Webinar Participant",
            "phone": "9876543231",
            "email": "participant@example.com",
            "city": "Hyderabad",
            "qualification": "B.Tech",
            "source": "webinar_page",
        }
        serializer = WebinarRegistrationSerializer(
            data=data,
            context={"webinar": webinar},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        mock_sync.assert_called_once()
        args, kwargs = mock_sync.call_args
        self.assertEqual(args[0].phone, "9876543231")
        self.assertEqual(kwargs.get("action_type"), "ACTION_1001")
        self.assertIn("Mastering Django", kwargs.get("action_note", ""))

    @patch("resources.views.sync_lead_to_telecrm")
    def test_resource_download_triggers_telecrm(self, mock_sync):
        from resources.models import Resources
        from resources.views import ResourcesViewSet

        resource = Resources.objects.create(
            title="Python Cheat Sheet",
            slug="python-cheat-sheet",
            status="active",
            form=True,
        )
        factory = APIRequestFactory()
        request = factory.post(
            f"/resources/{resource.slug}/download/",
            data={
                "name": "Resource Learner",
                "phone": "9876543241",
                "email": "learner@example.com",
                "city": "Mumbai",
            },
            format="json",
        )
        view = ResourcesViewSet.as_view({"post": "download"})
        response = view(request, slug=resource.slug)
        self.assertEqual(response.status_code, 200)

        mock_sync.assert_called_once()
        args, kwargs = mock_sync.call_args
        self.assertEqual(args[0].phone, "9876543241")
        self.assertEqual(kwargs.get("action_type"), "ACTION_1001")
        self.assertIn("Python Cheat Sheet", kwargs.get("action_note", ""))

    @patch("aryuapp.social_jwt.sync_lead_to_telecrm")
    def test_google_social_login_lead_creation_triggers_telecrm(self, mock_sync):
        from aryuapp.social_jwt import SocialLoginCompleteAPIView

        user = User.objects.create(
            username="social_new_user",
            email="social_new@example.com",
            full_name="Social User",
        )

        factory = APIRequestFactory()
        request = factory.get("/social/complete/")
        force_authenticate(request, user=user)

        view = SocialLoginCompleteAPIView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)

        lead = Lead.objects.filter(email="social_new@example.com").first()
        self.assertIsNotNone(lead)
        mock_sync.assert_called_once_with(
            lead,
            action_note="Lead Created via Google Social Login",
        )


class TeleCRMResilienceAndTransactionTestCase(TransactionTestCase):
    """
    Tests verifying transaction safety with on_commit and failure isolation.
    """

    @patch("requests.post")
    def test_telecrm_sync_runs_on_commit_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_response

        with transaction.atomic():
            lead = Lead.objects.create(
                name="Atomic Lead",
                phone="9876543251",
                status="fresh",
            )
            sync_lead_to_telecrm(lead, action_note="Atomic Test")
            # Inside the atomic block, requests.post should not have executed yet
            mock_post.assert_not_called()

        # After atomic block commits, on_commit hook executes
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_telecrm_sync_not_called_on_transaction_rollback(self, mock_post):
        try:
            with transaction.atomic():
                lead = Lead.objects.create(
                    name="Rollback Lead",
                    phone="9876543252",
                    status="fresh",
                )
                sync_lead_to_telecrm(lead, action_note="Rollback Test")
                raise ValueError("Intentional rollback")
        except ValueError:
            pass

        # Since transaction rolled back, on_commit hook must not execute
        mock_post.assert_not_called()
        self.assertEqual(Lead.objects.filter(phone="9876543252").count(), 0)

    @patch("requests.post")
    def test_external_telecrm_failure_does_not_break_lead_creation(self, mock_post):
        # Simulate external TeleCRM total outage / 500 error
        mock_post.side_effect = requests.ConnectionError("TeleCRM is down")

        # Database operation must still succeed without exception
        lead = Lead.objects.create(
            name="Resilient Lead",
            phone="9876543253",
            email="resilient@example.com",
            status="fresh",
        )
        sync_lead_to_telecrm(lead, action_note="Resilience Test", run_on_commit=False)

        lead.refresh_from_db()
        self.assertEqual(lead.name, "Resilient Lead")


@override_settings(
    CLOUDFLARE_TURNSTILE_SECRET_KEY="test-secret-key",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class PublicLeadTurnstileTestCase(TestCase):
    """
    Tests for Cloudflare Turnstile CAPTCHA in the Public Lead POST API.
    Verifies:
    1. captcha_token supplied + Cloudflare success -> Lead created.
    2. captcha_token supplied + Cloudflare rejection -> Lead NOT created.
    3. captcha_token supplied + expired/invalid response -> Lead NOT created.
    4. captcha_token supplied + Cloudflare timeout -> Lead NOT created.
    5. captcha_token supplied + Cloudflare/network error -> Lead NOT created.
    6. No captcha_token -> existing Lead flow works unchanged.
    7. No captcha_token with every relevant source/form type -> existing behavior remains unchanged.
    8. CAPTCHA token is not persisted in Lead.
    9. CAPTCHA token is not returned in API response.
    10. Existing Lead validation still works.
    11. Existing API response format remains unchanged for non-CAPTCHA requests.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PublicLeadViewSet.as_view({"post": "create"})

    @patch("lead.serializers.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_success_creates_lead(self, mock_cf_post, mock_sync):
        """
        1. captcha_token supplied + Cloudflare success -> Lead created.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Valid Captcha Lead",
                "phone": "9876543201",
                "email": "valid_cf@example.com",
                "city": "Chennai",
                "course": "Python Fullstack",
                "source": "website",
                "captcha_token": "cf-turnstile-valid-token",
            },
            format="json",
        )
        response = self.view(request)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data.get("success"))
        self.assertIn("lead_id", response.data)

        lead = Lead.objects.get(phone="9876543201")
        self.assertEqual(lead.name, "Valid Captcha Lead")
        self.assertEqual(lead.source, "website")
        mock_sync.assert_called_once()
        mock_cf_post.assert_called_once()

    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_rejection_lead_not_created(self, mock_cf_post):
        """
        2. captcha_token supplied + Cloudflare rejection -> Lead NOT created.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error-codes": ["invalid-input-response"],
        }
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Invalid Captcha Lead",
                "phone": "9876543202",
                "email": "invalid_cf@example.com",
                "source": "website",
                "captcha_token": "bogus-turnstile-token",
            },
            format="json",
        )
        response = self.view(request)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("verification failed", response.data.get("message", "").lower())
        self.assertEqual(Lead.objects.filter(phone="9876543202").count(), 0)

    @patch("requests.post")
    def test_captcha_token_supplied_expired_invalid_response_lead_not_created(self, mock_cf_post):
        """
        3. captcha_token supplied + expired/invalid response -> Lead NOT created.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error-codes": ["timeout-or-duplicate"],
        }
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Expired Captcha Lead",
                "phone": "9876543203",
                "email": "expired_cf@example.com",
                "source": "contact_us",
                "captcha_token": "expired-token-xyz",
            },
            format="json",
        )
        response = self.view(request)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(Lead.objects.filter(phone="9876543203").count(), 0)

    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_timeout_lead_not_created(self, mock_cf_post):
        """
        4. captcha_token supplied + Cloudflare timeout -> Lead NOT created.
        """
        mock_cf_post.side_effect = requests.Timeout("Cloudflare connection timed out")

        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Timeout Lead",
                "phone": "9876543204",
                "source": "landing_page",
                "captcha_token": "timeout-token-123",
            },
            format="json",
        )
        response = self.view(request)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("unavailable", response.data.get("message", "").lower())
        self.assertEqual(Lead.objects.filter(phone="9876543204").count(), 0)

    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_network_error_lead_not_created(self, mock_cf_post):
        """
        5. captcha_token supplied + Cloudflare/network error -> Lead NOT created.
        """
        mock_cf_post.side_effect = requests.ConnectionError("Network unreachable")

        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Network Error Lead",
                "phone": "9876543205",
                "source": "course_form",
                "captcha_token": "net-err-token",
            },
            format="json",
        )
        response = self.view(request)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("unavailable", response.data.get("message", "").lower())
        self.assertEqual(Lead.objects.filter(phone="9876543205").count(), 0)

    @patch("lead.serializers.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_no_captcha_token_existing_flow_works_unchanged(self, mock_cf_post, mock_sync):
        """
        6. No captcha_token -> existing Lead flow works unchanged (Cloudflare is NOT called).
        """
        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "No Captcha Lead",
                "phone": "9876543206",
                "email": "nocaptcha@example.com",
                "course": "Java Fullstack",
            },
            format="json",
        )
        response = self.view(request)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data.get("success"))
        self.assertEqual(Lead.objects.filter(phone="9876543206").count(), 1)
        mock_cf_post.assert_not_called()
        mock_sync.assert_called_once()

    @patch("lead.serializers.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_no_captcha_token_with_every_relevant_source_and_form_type(self, mock_cf_post, mock_sync):
        """
        7. No captcha_token with every relevant source/form type -> existing behavior remains unchanged.
        """
        sources_to_test = [
            "website",
            "contact_us",
            "website_form",
            "web",
            "meta_ads",
            "whatsapp",
            "landing_page",
            "course_enquiry",
            "walk-in",
            "referral",
        ]
        for idx, source_name in enumerate(sources_to_test):
            phone = f"98765432{idx:02d}"
            request = self.factory.post(
                "/api/lead/submit/",
                data={
                    "name": f"Lead {source_name}",
                    "phone": phone,
                    "source": source_name,
                    "course": "Python Fullstack",
                },
                format="json",
            )
            response = self.view(request)
            self.assertEqual(response.status_code, 201, f"Failed for source={source_name}")
            self.assertTrue(response.data.get("success"))
            lead = Lead.objects.get(phone=phone)
            self.assertEqual(lead.source, source_name)

        # Cloudflare should NEVER be called for any request without a captcha_token
        mock_cf_post.assert_not_called()

    @patch("lead.serializers.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_captcha_token_is_not_persisted_in_lead(self, mock_cf_post, mock_sync):
        """
        8. CAPTCHA token is not persisted in Lead model.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Persistence Check Lead",
                "phone": "9876543250",
                "captcha_token": "secret-turnstile-token-not-to-save",
            },
            format="json",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 201)

        lead = Lead.objects.get(phone="9876543250")
        self.assertFalse(hasattr(lead, "captcha_token"))

    @patch("lead.serializers.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_captcha_token_is_not_returned_in_api_response(self, mock_cf_post, mock_sync):
        """
        9. CAPTCHA token is not returned in API response.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Response Check Lead",
                "phone": "9876543251",
                "captcha_token": "should-never-appear-in-response",
            },
            format="json",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("captcha_token", response.data)
        self.assertNotIn("turnstile_token", response.data)

    @patch("requests.post")
    def test_existing_lead_validation_still_works_with_valid_captcha(self, mock_cf_post):
        """
        10a. Existing Lead validation still works when captcha is provided.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        # Phone with < 10 digits is invalid per validate_phone()
        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Invalid Phone With Captcha",
                "phone": "12345",
                "captcha_token": "valid-token",
            },
            format="json",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Lead.objects.filter(name="Invalid Phone With Captcha").count(), 0)

    def test_existing_lead_validation_still_works_without_captcha(self):
        """
        10b. Existing Lead validation still works when captcha is not provided.
        """
        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Invalid Phone Without Captcha",
                "phone": "12345",
            },
            format="json",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Lead.objects.filter(name="Invalid Phone Without Captcha").count(), 0)

    @patch("lead.serializers.sync_lead_to_telecrm")
    def test_existing_api_response_format_remains_unchanged_for_non_captcha_requests(self, mock_sync):
        """
        11. Existing API response format remains unchanged for non-CAPTCHA requests.
        """
        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Format Check Lead",
                "phone": "9876543252",
            },
            format="json",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data.keys()), {"success", "message", "lead_id"})
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "Lead submitted successfully.")
        self.assertIsInstance(response.data["lead_id"], int)

    @patch("lead.serializers.sync_lead_to_telecrm")
    @patch("requests.post")
    def test_alternative_turnstile_token_field_names(self, mock_cf_post, mock_sync):
        """
        Supports alternative token aliases: turnstile_token, turnstileToken, cf-turnstile-response.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        # Test turnstile_token
        req1 = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Alt Token 1",
                "phone": "9876543253",
                "turnstile_token": "alt-token-1",
            },
            format="json",
        )
        resp1 = self.view(req1)
        self.assertEqual(resp1.status_code, 201)

        # Test turnstileToken (camelCase)
        req2 = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Alt Token 2",
                "phone": "9876543254",
                "turnstileToken": "alt-token-2",
            },
            format="json",
        )
        resp2 = self.view(req2)
        self.assertEqual(resp2.status_code, 201)

        # Test cf-turnstile-response (Cloudflare form standard)
        req3 = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Alt Token 3",
                "phone": "9876543255",
                "cf-turnstile-response": "alt-token-3",
            },
            format="json",
        )
        resp3 = self.view(req3)
        self.assertEqual(resp3.status_code, 201)

    def test_empty_or_whitespace_captcha_token_supplied_is_rejected(self):
        """
        Supplying a blank or whitespace captcha_token counts as provided but invalid -> rejected.
        """
        request = self.factory.post(
            "/api/lead/submit/",
            data={
                "name": "Blank Token Lead",
                "phone": "9876543256",
                "captcha_token": "   ",
            },
            format="json",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(Lead.objects.filter(phone="9876543256").count(), 0)
