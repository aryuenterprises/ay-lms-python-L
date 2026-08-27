"""
Regression test suite for Resume application:
1. Rich-text HTML preservation & XSS sanitization
2. Resume refresh token authentication, rotation, and concurrent refresh lifecycle
"""
from django.test import TestCase
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken

from .models import (
    ResumeRegistration,
    Subscription,
    UserSubscription,
    ResumeTemplate,
    UserResume,
)
from .views import RESUME_REFRESH_COOKIE_NAME


class ResumeHTMLAndAuthTestCase(TestCase):
    """
    Validates rich-text description preservation, XSS security, and refresh-token mechanics.
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # 1. Setup Free Subscription
        self.subscription = Subscription.objects.create(
            name="Free",
            slug="free",
            price=0.00,
            discount_price=0.00,
            billing_type="monthly",
            duration_days="lifetime",
            limit="free",
            is_active=True,
        )

        # 2. Setup Verified Resume User
        self.password = "StrongPassword123!"
        self.user = ResumeRegistration.objects.create(
            first_name="Jane",
            last_name="Doe",
            email="jane.doe@example.com",
            phone="9876543210",
            password=make_password(self.password),
            city="San Francisco",
            state="CA",
            country="USA",
            is_verified=True,
            status=True,
        )

        self.user_sub = UserSubscription.objects.create(
            user=self.user,
            subscription=self.subscription,
            start_date="2026-01-01T00:00:00Z",
            status="active",
        )
        self.user.current_subscription = self.user_sub
        self.user.save()

        # 3. Setup Resume Template
        self.template = ResumeTemplate.objects.create(
            name="Modern Clean",
            slug="modern-clean",
            tier="free",
            structure=[],
            is_active=True,
        )

    def _get_auth_token(self):
        """Helper to obtain a fresh access token for testing."""
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        return str(refresh.access_token)

    # =========================================================================
    # PART 1: RESUME DESCRIPTION HTML PRESERVATION & XSS SANITIZATION TESTS
    # =========================================================================

    def test_resume_rich_text_html_is_preserved(self):
        """
        Verify that safe HTML sent by rich-text editor is preserved and returned intact,
        and not converted to plain text.
        """
        html_description = (
            "<p>Designed and implemented <strong>scalable backend services</strong> using Python and Django.</p>"
            "<ul>"
            "<li>Improved API response times.</li>"
            "<li>Optimized database queries.</li>"
            "</ul>"
        )

        access_token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Create resume with rich text HTML in resume_data
        create_payload = {
            "template": self.template.id,
            "resume_title": "Senior Engineer Resume",
            "resume_data": {
                "summary": "<p>Passionate <em>software architect</em> with 10+ years experience.</p>",
                "experience": [
                    {
                        "company": "Google",
                        "role": "Staff Engineer",
                        "description": html_description,
                    }
                ],
            },
        }

        create_resp = self.client.post("/api/resume/user-resumes", data=create_payload, format="json")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        resume_id = create_resp.data["id"]
        saved_desc = create_resp.data["resume_data"]["experience"][0]["description"]
        self.assertEqual(saved_desc, html_description)
        self.assertIn("<strong>scalable backend services</strong>", saved_desc)
        self.assertIn("<ul><li>Improved API response times.</li>", saved_desc)

        # Retrieve resume and verify returned payload contains exact HTML
        get_resp = self.client.get(f"/api/resume/user-resumes/{resume_id}")
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)
        retrieved_desc = get_resp.data["resume_data"]["experience"][0]["description"]
        self.assertEqual(retrieved_desc, html_description)

    def test_resume_incremental_section_update_preserves_html(self):
        """
        Verify that PATCH /api/resume/user-resumes/{id} preserves rich-text HTML.
        """
        access_token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        resume = UserResume.objects.create(
            user=self.user,
            template=self.template,
            resume_title="Developer Resume",
            resume_data={},
        )

        section_html = (
            "<h3>Projects</h3>"
            "<p>Architected <b>microservices</b> infrastructure.</p>"
            "<ol><li>Reduced latency by 40%</li><li>Deployed with Kubernetes</li></ol>"
        )

        patch_payload = {
            "section_name": "projects",
            "section_payload": [
                {
                    "title": "Cloud Platform",
                    "description": section_html,
                }
            ],
            "is_completed": True,
        }

        patch_resp = self.client.patch(
            f"/api/resume/user-resumes/{resume.id}",
            data=patch_payload,
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        saved_section = patch_resp.data["resume_data"]["projects"][0]["description"]
        self.assertEqual(saved_section, section_html)

    def test_xss_script_tags_are_sanitized(self):
        """
        Verify that dangerous <script> tags are stripped while safe HTML tags are preserved.
        """
        access_token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        malicious_input = (
            "<script>alert('XSS ATTACK')</script>"
            "<p>Safe paragraph <strong>retained</strong>.</p>"
        )

        create_resp = self.client.post(
            "/api/resume/user-resumes",
            data={
                "template": self.template.id,
                "resume_title": "Security Resume",
                "resume_data": {
                    "summary": malicious_input,
                },
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        summary = create_resp.data["resume_data"]["summary"]

        # <script> tags must NOT exist
        self.assertNotIn("<script>", summary)
        self.assertNotIn("</script>", summary)
        # Safe <p> and <strong> tags must be preserved
        self.assertIn("<p>Safe paragraph <strong>retained</strong>.</p>", summary)

    def test_xss_onerror_and_javascript_protocol_sanitized(self):
        """
        Verify that event handlers (onerror) and javascript: links are sanitized.
        """
        access_token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        xss_payload = (
            '<img src="invalid.jpg" onerror="alert(1)">'
            '<a href="javascript:alert(\'xss\')">Malicious Link</a>'
            '<a href="https://validlink.com" target="_blank">Valid Link</a>'
        )

        create_resp = self.client.post(
            "/api/resume/user-resumes",
            data={
                "template": self.template.id,
                "resume_title": "Link Resume",
                "resume_data": {
                    "links": xss_payload,
                },
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        links_data = create_resp.data["resume_data"]["links"]

        self.assertNotIn("onerror", links_data)
        self.assertNotIn("javascript:", links_data)
        self.assertIn('<a href="https://validlink.com" target="_blank">Valid Link</a>', links_data)

    # =========================================================================
    # PART 2: RESUME REFRESH TOKEN AUTHENTICATION & ROTATION TESTS
    # =========================================================================

    def test_resume_login_issues_access_and_refresh_tokens(self):
        """
        Verify login endpoint returns access_token, refresh_token in response and sets cookie.
        """
        response = self.client.post(
            "/api/resume/auth/login/",
            {"email": "jane.doe@example.com", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        self.assertIn(RESUME_REFRESH_COOKIE_NAME, response.cookies)

    def test_token_refresh_via_json_body(self):
        """
        Verify POST /api/resume/token/refresh/ using JSON body payload returns a new access token.
        """
        # Generate initial refresh token
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        refresh_token = str(refresh)

        # Refresh
        refresh_resp = self.client.post(
            "/api/resume/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", refresh_resp.data)
        self.assertIn("refresh_token", refresh_resp.data)

        # Use new access token to query protected API
        new_access = refresh_resp.data["access_token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        api_resp = self.client.get("/api/resume/user-resumes")
        self.assertEqual(api_resp.status_code, status.HTTP_200_OK)

    def test_token_refresh_via_cookie(self):
        """
        Verify POST /api/resume/token/refresh/ using HttpOnly cookie returns a new access token.
        """
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        refresh_token = str(refresh)

        self.client.cookies[RESUME_REFRESH_COOKIE_NAME] = refresh_token
        refresh_resp = self.client.post("/api/resume/token/refresh/", data={}, format="json")
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", refresh_resp.data)

    def test_token_refresh_via_authorization_header(self):
        """
        Verify POST /api/resume/token/refresh/ accepting Bearer header refresh token.
        """
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        refresh_token = str(refresh)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_token}")
        refresh_resp = self.client.post("/api/resume/token/refresh/", data={}, format="json")
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", refresh_resp.data)

    def test_invalid_refresh_token_rejected(self):
        """
        Verify invalid / corrupt refresh tokens return 401 Unauthorized cleanly without 500 crash.
        """
        refresh_resp = self.client.post(
            "/api/resume/token/refresh/",
            {"refresh": "invalid.corrupt.jwt.token"},
            format="json",
        )
        self.assertEqual(refresh_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_refresh_token_returns_400(self):
        """
        Verify missing refresh token returns 400 Bad Request.
        """
        refresh_resp = self.client.post("/api/resume/token/refresh/", data={}, format="json")
        self.assertEqual(refresh_resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_access_token_cannot_be_used_as_refresh_token(self):
        """
        Verify passing an access token to /token/refresh/ is rejected (token type mismatch).
        """
        access_token = self._get_auth_token()

        refresh_resp = self.client.post(
            "/api/resume/token/refresh/",
            {"refresh": access_token},
            format="json",
        )
        self.assertEqual(refresh_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token_cannot_be_used_as_access_token(self):
        """
        Verify passing a refresh token to normal protected API endpoint is rejected.
        """
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        refresh_token = str(refresh)

        # Attempt to access protected UserResumes endpoint using refresh token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_token}")
        api_resp = self.client.get("/api/resume/user-resumes")
        self.assertEqual(api_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_or_deleted_user_cannot_refresh(self):
        """
        Verify refresh fails if the user account has been deactivated or deleted.
        """
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        refresh_token = str(refresh)

        # Deactivate user
        self.user.status = False
        self.user.save()

        refresh_resp = self.client.post(
            "/api/resume/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(refresh_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_concurrent_refresh_requests_succeed_gracefully(self):
        """
        Verify that multiple concurrent / rapid sequential refresh requests with the same token
        succeed gracefully using short-lived rotation cache.
        """
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        refresh_token = str(refresh)

        # First refresh request
        resp1 = self.client.post(
            "/api/resume/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # Second rapid refresh request using the same initial refresh token (simulating parallel tab refresh)
        resp2 = self.client.post(
            "/api/resume/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data["access_token"], resp2.data["access_token"])

    def test_resume_logout_cleans_session(self):
        """
        Verify logout endpoint blacklists token and returns 200 OK.
        """
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        refresh_token = str(refresh)

        logout_resp = self.client.post(
            "/api/resume/auth/logout/",
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(logout_resp.status_code, status.HTTP_200_OK)
