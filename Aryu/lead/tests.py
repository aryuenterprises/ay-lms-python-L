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
from django.test import TestCase, TransactionTestCase
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
from lead.views import LeadViewSet


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
            action_type="ACTION_1002",
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
        self.assertEqual(actions[0]["type"], "ACTION_1002")
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
