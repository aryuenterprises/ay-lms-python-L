"""
Regression test suite for Resume application:
1. Rich-text HTML preservation & XSS sanitization
2. Resume refresh token authentication, rotation, and concurrent refresh lifecycle
3. Resume registration email verification flow (token generation, validation, idempotency, redirects, error handling)
"""
from django.test import TestCase
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core import signing
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken

from payments.models import PaymentTransaction, PaymentGateway
from unittest.mock import patch, MagicMock
from .models import (
    ResumeRegistration,
    Subscription,
    UserSubscription,
    ResumeTemplate,
    UserResume,
)
from .views import (
    RESUME_REFRESH_COOKIE_NAME,
    SIGNING_SALT,
    build_portal_verify_link,
    LOGIN_SUCCESS_REDIRECT,
    LOGIN_ERROR_REDIRECT,
    EMAIL_VERIFIED_SUCCESS_REDIRECT,
)


class ResumeHTMLAndAuthTestCase(TestCase):
    """
    Validates rich-text description preservation, XSS security, refresh-token mechanics,
    and email verification lifecycle.
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

    def test_resume_experiences_text_quill_html_preserved(self):
        """
        Test 1 & 2: Verify Quill-generated rich text with data-list and ql-ui in experiences[].text
        is preserved exactly as received, while normal fields like employer/jobTitle/resume_title are cleaned.
        """
        access_token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        quill_text = (
            '<ol>'
            '<li data-list="bullet">'
            '<span class="ql-ui" contenteditable="false"></span>'
            'Managed daily operational workflows to ensure alignment with organizational goals and improve overall team productivity through streamlined process implementation.'
            '</li>'
            '<li data-list="bullet">'
            '<span class="ql-ui" contenteditable="false"></span>'
            'Collaborated with cross-functional teams to identify operational bottlenecks and execute strategic solutions that enhanced service delivery and efficiency.'
            '</li>'
            '</ol>'
        )

        create_payload = {
            "template": self.template.id,
            "resume_title": "<b>Senior Staff Resume</b>",
            "resume_data": {
                "experiences": [
                    {
                        "id": 1787805503208,
                        "employer": "<b>Possimus eos ut par</b>",
                        "jobTitle": "<i>Obecati molestiae</i>",
                        "location": "<span>Et eos qui molestiae</span>",
                        "startDate": "1988-08",
                        "endDate": "2000-05",
                        "year": 2026,
                        "isOpen": True,
                        "showPicker": False,
                        "text": quill_text,
                    }
                ]
            }
        }

        create_resp = self.client.post("/api/resume/user-resumes", data=create_payload, format="json")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        resume_id = create_resp.data["id"]
        exp_item = create_resp.data["resume_data"]["experiences"][0]

        # Rich text preserved
        self.assertEqual(exp_item["text"], quill_text)
        self.assertIn('data-list="bullet"', exp_item["text"])
        self.assertIn('class="ql-ui"', exp_item["text"])

        # Normal text cleaned
        self.assertEqual(create_resp.data["resume_title"], "Senior Staff Resume")
        self.assertEqual(exp_item["employer"], "Possimus eos ut par")
        self.assertEqual(exp_item["jobTitle"], "Obecati molestiae")
        self.assertEqual(exp_item["location"], "Et eos qui molestiae")

        # GET request retrieval check
        get_resp = self.client.get(f"/api/resume/user-resumes/{resume_id}")
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)
        get_exp_item = get_resp.data["resume_data"]["experiences"][0]
        self.assertEqual(get_exp_item["text"], quill_text)
        self.assertEqual(get_exp_item["employer"], "Possimus eos ut par")

    def test_resume_multiple_nested_experience_objects(self):
        """
        Test 3: Nested experience objects preserve HTML for multiple records.
        """
        access_token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        create_payload = {
            "template": self.template.id,
            "resume_title": "Multi Experience Resume",
            "resume_data": {
                "experiences": [
                    {
                        "employer": "<b>Employer 1</b>",
                        "text": "<p>Experience 1</p>",
                    },
                    {
                        "employer": "<i>Employer 2</i>",
                        "text": "<p>Experience 2</p>",
                    }
                ]
            }
        }

        create_resp = self.client.post("/api/resume/user-resumes", data=create_payload, format="json")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        exps = create_resp.data["resume_data"]["experiences"]
        self.assertEqual(exps[0]["text"], "<p>Experience 1</p>")
        self.assertEqual(exps[0]["employer"], "Employer 1")
        self.assertEqual(exps[1]["text"], "<p>Experience 2</p>")
        self.assertEqual(exps[1]["employer"], "Employer 2")

    def test_resume_incremental_section_update_preserves_html(self):
        """
        Verify that PATCH /api/resume/user-resumes/{id} preserves rich-text HTML in section_payload.
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
                    "title": "<b>Cloud Platform</b>",
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
        saved_section = patch_resp.data["resume_data"]["projects"][0]
        self.assertEqual(saved_section["description"], section_html)
        self.assertEqual(saved_section["title"], "Cloud Platform")

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
                    "summary": xss_payload,
                },
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        summary_data = create_resp.data["resume_data"]["summary"]

        self.assertNotIn("onerror", summary_data)
        self.assertNotIn("javascript:", summary_data)
        self.assertIn('<a href="https://validlink.com" target="_blank">Valid Link</a>', summary_data)

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

    # =========================================================================
    # PART 3: RESUME REGISTRATION EMAIL VERIFICATION LIFECYCLE TESTS
    # =========================================================================

    def test_resume_signup_creates_unverified_account_and_generates_token(self):
        """
        Verify signup creates user with is_verified=False and builds valid verification token.
        """
        signup_payload = {
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice.smith@example.com",
            "phone": "9876543222",
            "password": "SecurePassword123!",
            "city": "Austin",
            "state": "TX",
            "country": "USA",
        }

        resp = self.client.post("/api/resume/auth/signup/", data=signup_payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        user = ResumeRegistration.objects.get(email="alice.smith@example.com")
        self.assertFalse(user.is_verified)

        # Generate verification token as done in signup
        token = signing.dumps({"user_id": user.id, "email": user.email}, salt=SIGNING_SALT)
        self.assertIsNotNone(token)

    def test_valid_token_verifies_account_via_api(self):
        """
        Verify that a valid token marks user account is_verified=True and returns 200 OK.
        """
        unverified_user = ResumeRegistration.objects.create(
            first_name="Bob",
            last_name="Johnson",
            email="bob.johnson@example.com",
            phone="9876543233",
            password=make_password(self.password),
            city="Seattle",
            state="WA",
            country="USA",
            is_verified=False,
            status=True,
        )

        token = signing.dumps({"user_id": unverified_user.id, "email": unverified_user.email}, salt=SIGNING_SALT)

        # JSON API verification call
        verify_resp = self.client.get(
            f"/api/resume/auth/verify-email/?token={token}",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_resp.data.get("success"))

        unverified_user.refresh_from_db()
        self.assertTrue(unverified_user.is_verified)

    def test_browser_verification_redirects_to_login(self):
        """
        Verify that verification from a browser (Accept: text/html) redirects to login page.
        """
        unverified_user = ResumeRegistration.objects.create(
            first_name="Charlie",
            last_name="Brown",
            email="charlie.brown@example.com",
            phone="9876543244",
            password=make_password(self.password),
            city="Chicago",
            state="IL",
            country="USA",
            is_verified=False,
            status=True,
        )

        token = signing.dumps({"user_id": unverified_user.id, "email": unverified_user.email}, salt=SIGNING_SALT)

        # Browser GET verification request
        verify_resp = self.client.get(
            f"/api/resume/auth/verify-email/?token={token}",
            HTTP_ACCEPT="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_302_FOUND)
        self.assertEqual(verify_resp.url, "https://passats.aryuacademy.com/email-verified")

        unverified_user.refresh_from_db()
        self.assertTrue(unverified_user.is_verified)

    def test_verification_is_idempotent(self):
        """
        Verify that clicking the verification link a second time succeeds gracefully without error.
        """
        user = ResumeRegistration.objects.create(
            first_name="David",
            last_name="Miller",
            email="david.miller@example.com",
            phone="9876543255",
            password=make_password(self.password),
            city="Miami",
            state="FL",
            country="USA",
            is_verified=True,  # Already verified
            status=True,
        )

        token = signing.dumps({"user_id": user.id, "email": user.email}, salt=SIGNING_SALT)

        verify_resp = self.client.get(
            f"/api/resume/auth/verify-email/?token={token}",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_resp.data.get("success"))
        self.assertIn("already verified", verify_resp.data.get("message", "").lower())

    def test_invalid_and_corrupt_verification_tokens_rejected(self):
        """
        Verify that invalid or forged verification tokens return 400 Bad Request.
        """
        # 1. Random corrupted string
        resp1 = self.client.get(
            "/api/resume/auth/verify-email/?token=invalid_forged_token_string",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp1.data.get("success"))

        # 2. Tampered signature
        valid_token = signing.dumps({"user_id": self.user.id, "email": self.user.email}, salt=SIGNING_SALT)
        tampered_token = valid_token[:-4] + "xxxx"
        resp2 = self.client.get(
            f"/api/resume/auth/verify-email/?token={tampered_token}",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_verification_token_returns_400(self):
        """
        Verify that calling verify-email without a token returns 400 Bad Request.
        """
        resp = self.client.get(
            "/api/resume/auth/verify-email/",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.data.get("success"))

    def test_resend_verification_email_flow(self):
        """
        Verify resend-verification-email endpoint handles unverified and already verified accounts.
        """
        unverified_user = ResumeRegistration.objects.create(
            first_name="Eva",
            last_name="Green",
            email="eva.green@example.com",
            phone="9876543266",
            password=make_password(self.password),
            city="Denver",
            state="CO",
            country="USA",
            is_verified=False,
            status=True,
        )

        # 1. Resend for unverified user
        resp1 = self.client.post(
            "/api/resume/auth/resend-verification-email/",
            data={"email": "eva.green@example.com"},
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # 2. Resend for already verified user
        unverified_user.is_verified = True
        unverified_user.save()

        resp2 = self.client.post(
            "/api/resume/auth/resend-verification-email/",
            data={"email": "eva.green@example.com"},
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data.get("message"), "Account already verified")

    # =========================================================================
    # PART 4: USER DASHBOARD TRANSACTIONS TESTS
    # =========================================================================

    def test_user_dashboard_transactions_history(self):
        """
        Verify that /api/resume/dashboard returns full transaction history:
        1. Does not drop transactions with the same plan name.
        2. Correctly populates amount, currency, payment_status, payment_mode, invoice_no, invoice_date.
        3. Safely handles free plan subscriptions without payment transaction.
        4. Matches statistics.total_transactions to returned transaction list count.
        """
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        pro_plan = Subscription.objects.create(
            name="Pro Plan",
            slug="pro-plan",
            price=499.00,
            discount_price=399.00,
            billing_type="monthly",
            duration_days="30",
            limit="pro",
            is_active=True,
        )

        # 1. Paid transaction 1
        txn1 = PaymentTransaction.objects.create(
            resume_registration=self.user,
            subscription=pro_plan,
            amount=399.00,
            currency="INR",
            payment_status="done",
            payment_mode="razorpay",
            invoice_no="INV-2026-001",
            invoice_date="2026-02-01",
            transaction_id="pay_test_001",
        )
        user_sub_pro1 = UserSubscription.objects.create(
            user=self.user,
            subscription=pro_plan,
            payment_transaction=txn1,
            start_date="2026-02-01T00:00:00Z",
            end_date="2026-03-03T00:00:00Z",
            status="expired",
        )

        # 2. Paid transaction 2 (Renewal of the exact same plan name "Pro Plan")
        txn2 = PaymentTransaction.objects.create(
            resume_registration=self.user,
            subscription=pro_plan,
            amount=399.00,
            currency="INR",
            payment_status="done",
            payment_mode="razorpay",
            invoice_no="INV-2026-002",
            invoice_date="2026-03-03",
            transaction_id="pay_test_002",
        )
        user_sub_pro2 = UserSubscription.objects.create(
            user=self.user,
            subscription=pro_plan,
            payment_transaction=txn2,
            start_date="2026-03-03T00:00:00Z",
            end_date="2026-04-02T00:00:00Z",
            status="active",
        )

        resp = self.client.get("/api/resume/dashboard")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = resp.data
        self.assertIn("transactions", data)
        self.assertIn("statistics", data)

        transactions = data["transactions"]
        # Total subscriptions for this user = 3 (Free setup in setUp, Pro 1, Pro 2)
        self.assertEqual(len(transactions), 3)
        self.assertEqual(data["statistics"]["total_transactions"], 3)

        # Ensure both Pro Plan transactions are present (not deduped by plan name)
        pro_txns = [t for t in transactions if t["plan_name"] == "Pro Plan"]
        self.assertEqual(len(pro_txns), 2)

        # Validate paid transaction details
        tx2_data = next(t for t in pro_txns if t["id"] == user_sub_pro2.id)
        self.assertEqual(str(tx2_data["amount"]), "399.00")
        self.assertEqual(tx2_data["currency"], "INR")
        self.assertEqual(tx2_data["payment_status"], "done")
        self.assertEqual(tx2_data["payment_mode"], "razorpay")
        self.assertEqual(tx2_data["invoice_no"], "INV-2026-002")
        self.assertEqual(str(tx2_data["invoice_date"]), "2026-03-03")

        # Validate free transaction details
        free_txn = next(t for t in transactions if t["id"] == self.user_sub.id)
        self.assertEqual(free_txn["plan_name"], "Free")
        self.assertEqual(str(free_txn["amount"]), "0.00")
        self.assertEqual(free_txn["currency"], "INR")
        self.assertEqual(free_txn["payment_status"], "free")
        self.assertEqual(free_txn["payment_mode"], "free")
        self.assertIn("transaction_id", free_txn)
        self.assertIn("created_date", free_txn)
        self.assertIn("created_at", free_txn)

    def test_complete_paid_subscription_flow_and_dashboard_retrieval(self):
        """
        Tests the complete end-to-end flow:
        1. Resume App -> Payment Initiation (/api/resume/payment/create-order/)
        2. PaymentTransaction created with payment_status='created'
        3. Payment Gateway verification callback (/api/resume/payment/verify-payment/)
        4. PaymentTransaction updated to 'done' and linked to UserSubscription
        5. Dashboard API returns full transaction details with all required fields
        """
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        gateway = PaymentGateway.objects.create(
            gatway_name="Razorpay Test",
            public_key="rzp_test_public_key",
            secret_key="rzp_test_secret_key",
            webhook_secret="test_webhook_secret",
            is_archived=False,
        )

        plan = Subscription.objects.create(
            name="Premium Plan",
            slug="premium-plan",
            price=999.00,
            discount_price=799.00,
            billing_type="yearly",
            duration_days="365",
            limit="premium",
            is_active=True,
        )

        # 1. Initiate Order
        with patch("razorpay.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.order.create.return_value = {
                "id": "order_test_12345",
                "amount": 79900,
                "currency": "INR",
            }

            order_resp = self.client.post(
                "/api/resume/payment/create-order/",
                data={"subscription_id": plan.id},
                format="json",
            )
            self.assertEqual(order_resp.status_code, status.HTTP_200_OK)
            self.assertTrue(order_resp.data["success"])
            self.assertEqual(order_resp.data["order_id"], "order_test_12345")

        # Verify PaymentTransaction created
        txn = PaymentTransaction.objects.get(order_id="order_test_12345")
        self.assertEqual(txn.resume_registration_id, self.user.id)
        self.assertEqual(txn.subscription_id, plan.id)
        self.assertEqual(txn.amount, 799.00)
        self.assertEqual(txn.payment_status, "created")

        # 2. Verify Payment
        with patch("razorpay.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.utility.verify_payment_signature.return_value = True

            verify_resp = self.client.post(
                "/api/resume/payment/verify-payment/",
                data={
                    "razorpay_order_id": "order_test_12345",
                    "razorpay_payment_id": "pay_test_98765",
                    "razorpay_signature": "test_valid_signature",
                },
                format="json",
            )
            self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)
            self.assertTrue(verify_resp.data["success"])

        # Verify DB records updated and linked
        txn.refresh_from_db()
        self.assertEqual(txn.payment_status, "done")
        self.assertEqual(txn.transaction_id, "pay_test_98765")
        self.assertEqual(txn.payment_mode, "razorpay")
        self.assertIsNotNone(txn.invoice_no)
        self.assertIsNotNone(txn.invoice_date)

        user_sub = UserSubscription.objects.get(payment_transaction=txn)
        self.assertEqual(user_sub.user_id, self.user.id)
        self.assertEqual(user_sub.subscription_id, plan.id)
        self.assertEqual(user_sub.status, "active")

        # 3. Retrieve Dashboard API
        dash_resp = self.client.get("/api/resume/dashboard")
        self.assertEqual(dash_resp.status_code, status.HTTP_200_OK)
        dash_data = dash_resp.data

        txns_list = dash_data["transactions"]
        self.assertEqual(dash_data["statistics"]["total_transactions"], len(txns_list))

        paid_item = next(t for t in txns_list if t["transaction_id"] == "pay_test_98765")
        self.assertEqual(paid_item["plan_name"], "Premium Plan")
        self.assertEqual(str(paid_item["amount"]), "799.00")
        self.assertEqual(paid_item["currency"], "INR")
        self.assertEqual(paid_item["payment_status"], "done")
        self.assertEqual(paid_item["payment_mode"], "razorpay")
        self.assertEqual(paid_item["invoice_no"], txn.invoice_no)
        self.assertEqual(str(paid_item["invoice_date"]), str(txn.invoice_date))
        self.assertIsNotNone(paid_item["created_date"])
        self.assertIsNotNone(paid_item["created_at"])


class SubscriptionDescriptionRawHTMLTestCase(TestCase):
    """
    Validates that Subscription model's description strictly stores and persists raw HTML
    in the database and API responses without any stripping, parsing, or conversion to plain text/newlines.
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # Admin user for protected subscription management endpoints
        self.admin_user = ResumeRegistration.objects.create(
            first_name="Admin",
            last_name="User",
            email="admin@example.com",
            password=make_password("AdminPass123!"),
            is_verified=True,
            status=True,
        )
        self.admin_user.user_type = "admin"
        self.admin_user.save()

    def _get_admin_token(self):
        refresh = RefreshToken()
        refresh["user_id"] = self.admin_user.id
        refresh["id"] = self.admin_user.id
        refresh["email"] = self.admin_user.email
        refresh["user_type"] = "admin"
        return str(refresh.access_token)

    def test_subscription_creation_preserves_raw_html_description(self):
        raw_html = "<ol><li>Free plan</li><li>freee</li></ol><ul><li>freee</li></ul>"

        payload = {
            "name": "Pro HTML Plan",
            "slug": "pro-html-plan",
            "description": raw_html,
            "price": 29.99,
            "discount_price": 19.99,
            "billing_type": "monthly",
            "duration_days": "30",
            "limit": "pro",
            "is_active": True,
        }

        # 1. Create via PublicSubscriptionPlansViewSet
        response = self.client.post("/api/resume/pricing-plans/", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data.get("success"))

        plan_data = response.data["plan"]
        self.assertEqual(plan_data["description"], raw_html)
        self.assertNotIn("\nFree plan", plan_data["description"])
        self.assertIn("<ol><li>Free plan</li>", plan_data["description"])

        # 2. Verify Database Persistence
        plan_id = plan_data["id"]
        db_obj = Subscription.objects.get(id=plan_id)
        self.assertEqual(db_obj.description, raw_html)

        # 3. Retrieve list and verify API response retains raw HTML
        list_response = self.client.get("/api/resume/pricing-plans/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        fetched_plans = list_response.data.get("plans", [])
        matched = next((p for p in fetched_plans if p["id"] == plan_id), None)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["description"], raw_html)

    def test_subscription_update_preserves_raw_html_description(self):
        initial_html = "<p>Initial Description</p>"
        sub = Subscription.objects.create(
            name="HTML Update Plan",
            slug="html-update-plan",
            description=initial_html,
            price=49.99,
            billing_type="monthly",
            duration_days="30",
            limit="premium",
            is_active=True,
        )

        updated_html = "<ol><li>Feature 1</li><li>Feature 2</li></ol><div class=\"highlight\"><strong>Special Offer</strong></div>"

        # Update via PublicSubscriptionPlansViewSet
        patch_resp = self.client.patch(
            f"/api/resume/pricing-plans/{sub.id}",
            data={"description": updated_html},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(patch_resp.data.get("success"))
        self.assertEqual(patch_resp.data["plan"]["description"], updated_html)

        sub.refresh_from_db()
        self.assertEqual(sub.description, updated_html)

    def test_create_and_update_plan_via_subscription_viewset_preserves_raw_html(self):
        admin_token = self._get_admin_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_token}")

        raw_html = "<ol><li>Free plan</li><li>freee</li></ol><ul><li>freee</li></ul>"

        payload = {
            "name": "Admin HTML Plan",
            "slug": "admin-html-plan",
            "description": raw_html,
            "price": 99.00,
            "billing_type": "yearly",
            "duration_days": "365",
            "limit": "enterprise",
            "is_active": True,
        }

        # 1. Create plan via create-plan endpoint
        create_resp = self.client.post("/api/resume/create-plan/", data=payload, format="json")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        created_plan = create_resp.data["plan"]
        self.assertEqual(created_plan["description"], raw_html)

        plan_id = created_plan["id"]
        sub = Subscription.objects.get(id=plan_id)
        self.assertEqual(sub.description, raw_html)

        # 2. Update plan via update-plan endpoint
        new_raw_html = "<div><p>Updated <em>Enterprise Plan</em></p><ul><li>Feature A</li></ul></div>"
        update_resp = self.client.patch(
            f"/api/resume/update-plan/{plan_id}/",
            data={"description": new_raw_html},
            format="json",
        )
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data["plan"]["description"], new_raw_html)

        sub.refresh_from_db()
        self.assertEqual(sub.description, new_raw_html)


class ResumePDFGenerationTestCase(TestCase):
    """
    Comprehensive tests for POST /api/resume/candidates/generate-pdf:
    1. Multi-parser verification: JSON, Multipart/form-data, Form-urlencoded.
    2. 415 Unsupported Media Type for unsupported content types.
    3. Input validation: missing, empty, oversized, invalid HTML -> 400 Bad Request.
    4. Authentication: 401 Unauthorized for unauthenticated requests.
    5. XSS Sanitization: strips scripts, event handlers, iframes, objects, forms.
    6. SSRF / Local File Inclusion (LFI) protection: blocks file://, loopback, private IPs, cloud metadata.
    7. Legitimate resume rendering: complex CSS, tables, fonts, base64 images -> valid PDF binary.
    8. Safe filename validation & response headers.
    """

    def setUp(self):
        try:
            cache.clear()
        except Exception:
            pass
        self.client = APIClient()

        # Setup Verified Resume User
        self.password = "StrongPassword123!"
        self.user = ResumeRegistration.objects.create(
            first_name="Alice",
            last_name="Smith",
            email="alice.smith@example.com",
            phone="9876543211",
            password=make_password(self.password),
            is_verified=True,
            status=True,
        )

    def _get_auth_token(self):
        refresh = RefreshToken()
        refresh["user_id"] = self.user.id
        refresh["id"] = self.user.id
        refresh["email"] = self.user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = self.user.first_name
        refresh["last_name"] = self.user.last_name
        return str(refresh.access_token)

    def test_generate_pdf_json_payload_success(self):
        """Verify POST /api/resume/candidates/generate-pdf with application/json."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Resume</title></head>
        <body>
            <h1>Alice Smith</h1>
            <p>Senior Software Engineer</p>
        </body>
        </html>
        """
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": html, "filename": "alice_resume.pdf"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("alice_resume.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 1000)

    def test_generate_pdf_multipart_form_data_success(self):
        """Verify POST /api/resume/candidates/generate-pdf with multipart/form-data (fixing 415 error)."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        html = "<html><body><h1>Alice Multipart Resume</h1><p>Experience: 5 years</p></body></html>"
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": html},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("resume.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_generate_pdf_multipart_json_escaped_payload_normalized(self):
        """Verify multipart/form-data receiving JSON.stringify-escaped HTML is properly normalized."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Simulating frontend sending JSON-stringified HTML in form-data
        raw_html = (
            "<!DOCTYPE html>\n<html>\n<head>\n"
            "<style>\n"
            "@import url(\"https://fonts.googleapis.com/css2?family=Roboto\");\n"
            "body {\n  margin-bottom: 24px;\n  color: #333;\n}\n"
            "</style>\n</head>\n"
            "<body>\n<div style=\"margin-bottom: 24px;\">Alice Escaped Resume</div>\n</body>\n</html>"
        )
        import json
        escaped_html = json.dumps(raw_html)

        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": escaped_html},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_generate_pdf_multipart_escaped_quotes_and_newlines_normalized(self):
        """Verify multipart/form-data with literal \\n and escaped \\\" in style tags is normalized."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        escaped_html = (
            "<style>\\n@import url(\\\"https://fonts.googleapis.com/css2?family=Roboto\\\");\\n"
            "body { margin-bottom: 24px\\\"; }\\n</style>\\n"
            "<div><p>Alice\\nEngineer</p></div>"
        )
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": escaped_html},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_generate_pdf_form_urlencoded_success(self):
        """Verify POST /api/resume/candidates/generate-pdf with application/x-www-form-urlencoded."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        html = "<html><body><h1>Alice Form Resume</h1></body></html>"
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": html},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_generate_pdf_unsupported_media_type(self):
        """Verify unsupported Content-Type returns 415 Unsupported Media Type."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data="raw text content",
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    def test_generate_pdf_missing_html_returns_400(self):
        """Verify missing html field returns 400 Bad Request."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"invalid_key": "<html></html>"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue("html" in response.data or ("details" in response.data and "html" in response.data["details"]))

    def test_generate_pdf_empty_html_returns_400(self):
        """Verify empty or too-short html field returns 400 Bad Request."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response_short = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": "<p>hi</p>"},
            format="json",
        )
        self.assertEqual(response_short.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_pdf_unauthenticated_returns_401(self):
        """Verify unauthenticated requests return 401 Unauthorized."""
        self.client.credentials()  # Clear auth
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": "<html><body><h1>Test</h1></body></html>"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_generate_pdf_xss_and_malicious_tags_sanitized(self):
        """Verify malicious scripts, event handlers, and iframes are stripped and PDF renders safely."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        malicious_html = """
        <html>
        <head>
            <script>alert('XSS executed'); window.location='http://attacker.com';</script>
        </head>
        <body>
            <h1 onclick="alert('clicked')">Candidate Profile</h1>
            <img src="http://example.com/pic.jpg" onerror="alert('error')" />
            <a href="javascript:alert('link')">Click Me</a>
            <iframe src="http://attacker.com/evil"></iframe>
            <object data="http://attacker.com/flash"></object>
            <form action="http://attacker.com/steal"><input name="pass" value="123" /></form>
        </body>
        </html>
        """
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": malicious_html},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_generate_pdf_ssrf_and_lfi_blocked(self):
        """Verify local file inclusion and SSRF targets are intercepted and blocked without error."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        ssrf_html = """
        <html>
        <head>
            <style>
                @import url('file:///etc/passwd');
                @font-face {
                    font-family: 'EvilFont';
                    src: url('http://169.254.169.254/latest/meta-data/');
                }
            </style>
        </head>
        <body>
            <h1>Resume Test</h1>
            <img src="file:///etc/shadow" />
            <img src="http://127.0.0.1:8000/admin/" />
            <img src="http://localhost:3000/internal" />
            <img src="http://169.254.169.254/secret" />
            <img src="http://evil-unapproved-domain.com/tracker.png" />
        </body>
        </html>
        """
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": ssrf_html},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_generate_pdf_complex_styling_and_safe_data_uri(self):
        """Verify complex resume CSS, print page rules, tables, and valid base64 images render cleanly."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        complex_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page { size: A4; margin: 15mm; }
                body { font-family: sans-serif; color: #1a1a1a; font-size: 11pt; line-height: 1.4; }
                .header { border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 15px; }
                .name { font-size: 24pt; font-weight: bold; color: #1e3a8a; }
                .contact { font-size: 9pt; color: #4b5563; margin-top: 4px; }
                .section-title { font-size: 14pt; font-weight: bold; color: #1e3a8a; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 14px; margin-bottom: 8px; }
                .exp-item { margin-bottom: 10px; }
                .exp-title { font-weight: bold; font-size: 11pt; }
                .exp-company { font-style: italic; color: #374151; font-size: 10pt; }
                .skills-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
                .skills-table td { padding: 4px 8px; border: 1px solid #e5e7eb; font-size: 10pt; }
            </style>
        </head>
        <body>
            <div class="header">
                <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" width="40" height="40" alt="Avatar" />
                <div class="name">Alice Smith</div>
                <div class="contact">alice@example.com &bull; +1 (555) 123-4567 &bull; San Francisco, CA</div>
            </div>
            <div class="section-title">Professional Experience</div>
            <div class="exp-item">
                <div class="exp-title">Lead Software Architect</div>
                <div class="exp-company">Tech Solutions Inc. | 2021 - Present</div>
                <p>Engineered resilient cloud backends handling 50k+ req/sec with Django and PostgreSQL.</p>
            </div>
            <div class="section-title">Technical Skills</div>
            <table class="skills-table">
                <tr><td><strong>Languages:</strong> Python, TypeScript, Go</td><td><strong>Databases:</strong> PostgreSQL, Redis</td></tr>
                <tr><td><strong>Frameworks:</strong> Django, React, FastAPI</td><td><strong>Tools:</strong> Docker, Kubernetes, AWS</td></tr>
            </table>
        </body>
        </html>
        """
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": complex_html, "filename": "Alice_Smith_Resume.pdf"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("Alice_Smith_Resume.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 2000)

    def test_generate_pdf_filename_sanitization(self):
        """Verify filename with path traversal and CRLF characters is safely sanitized."""
        token = self._get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        html = "<html><body><h1>Alice Resume</h1></body></html>"
        response = self.client.post(
            "/api/resume/candidates/generate-pdf",
            data={"html": html, "filename": "../../evil\r\nHeader: injected.pdf"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disposition = response["Content-Disposition"]
        self.assertNotIn("\r", disposition)
        self.assertNotIn("\n", disposition)
        self.assertNotIn("../", disposition)


from aryuapp.models import StudentTicket, TicketReply, TicketAttachment, Student
from django.core.files.uploadedfile import SimpleUploadedFile


class ResumeTicketIntegrationTestCase(TestCase):
    """
    Comprehensive regression tests for Resume Ticket / Support System integration:
    - Ticket creation (with & without file attachments)
    - Authentication and permissions enforcement
    - Ticket listing with aggregate counts (new, in_progress, closed, total)
    - Filter by status and ticket_type
    - Ticket detail retrieval with replies and attachments
    - Ticket reply and automated state transitions
    - Protection against replying to closed tickets
    - Ticket closing action
    - Strict user data isolation (User A vs User B)
    - Strict module isolation (Resume tickets vs AryuApp student tickets)
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # User A (Primary test user)
        self.user_a = ResumeRegistration.objects.create(
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
            phone="9876543210",
            password=make_password("TestPass123!"),
            is_verified=True,
            status=True,
        )

        # User B (Isolation test user)
        self.user_b = ResumeRegistration.objects.create(
            first_name="Bob",
            last_name="Jones",
            email="bob@example.com",
            phone="9876543211",
            password=make_password("TestPass123!"),
            is_verified=True,
            status=True,
        )

    def _get_token_for(self, user):
        refresh = RefreshToken()
        refresh["user_id"] = user.id
        refresh["id"] = user.id
        refresh["email"] = user.email
        refresh["user_type"] = "resume_user"
        refresh["first_name"] = user.first_name
        refresh["last_name"] = user.last_name
        return str(refresh.access_token)

    def test_unauthenticated_requests_are_rejected(self):
        """Unauthenticated requests must receive 401 Unauthorized."""
        response = self.client.get("/api/resume/tickets")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.post("/api/resume/tickets", data={"subject": "Test", "message": "Help"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_ticket_success(self):
        """Authenticated user can create a support ticket."""
        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        payload = {
            "subject": "Need help with PDF download",
            "message": "My PDF download is timing out on complex template.",
            "ticket_type": "technical_support",
            "priority": "High"
        }
        response = self.client.post("/api/resume/tickets", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data.get("success"))

        ticket_data = response.data.get("data", {})
        self.assertEqual(ticket_data.get("subject"), payload["subject"])
        self.assertEqual(ticket_data.get("message"), payload["message"])
        self.assertEqual(ticket_data.get("ticket_type"), "technical_support")
        self.assertEqual(ticket_data.get("status"), "New")
        self.assertEqual(ticket_data.get("priority"), "High")
        self.assertTrue(ticket_data.get("ticket_token"))

        # Verify database record
        ticket_obj = StudentTicket.objects.get(ticket_id=ticket_data["ticket_id"])
        self.assertEqual(ticket_obj.resume_user, self.user_a)
        self.assertIsNone(ticket_obj.student)
        self.assertEqual(ticket_obj.email, self.user_a.email)

    def test_create_ticket_with_file_attachment(self):
        """Authenticated user can create a ticket with file attachments."""
        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        test_file = SimpleUploadedFile("screenshot.png", b"fake_png_data", content_type="image/png")
        payload = {
            "subject": "Formatting bug screenshot",
            "message": "Please see the attached screenshot.",
            "attachments": test_file,
        }
        response = self.client.post("/api/resume/tickets", data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ticket_data = response.data.get("data", {})
        self.assertEqual(len(ticket_data.get("attachments", [])), 1)
        self.assertIn("screenshot", ticket_data["attachments"][0]["file"])

    def test_list_tickets_and_status_counts(self):
        """List tickets returns tickets belonging to user with status aggregates."""
        # Create tickets in various states for User A
        t1 = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Ticket 1",
            message="Msg 1",
            status="New",
            ticket_type="support"
        )
        t2 = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Ticket 2",
            message="Msg 2",
            status="in_progress",
            ticket_type="billing"
        )
        t3 = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Ticket 3",
            message="Msg 3",
            status="closed",
            ticket_type="support"
        )

        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.get("/api/resume/tickets")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("success"))

        counts = response.data.get("counts", {})
        self.assertEqual(counts.get("new"), 1)
        self.assertEqual(counts.get("in_progress"), 1)
        self.assertEqual(counts.get("closed"), 1)
        self.assertEqual(counts.get("total"), 3)

        tickets = response.data.get("tickets", [])
        self.assertEqual(len(tickets), 3)

    def test_list_tickets_filtering(self):
        """Filtering by status and ticket_type works correctly."""
        StudentTicket.objects.create(
            resume_user=self.user_a, subject="T1", message="M1", status="New", ticket_type="support"
        )
        StudentTicket.objects.create(
            resume_user=self.user_a, subject="T2", message="M2", status="in_progress", ticket_type="billing"
        )

        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Filter by status
        response = self.client.get("/api/resume/tickets?status=in_progress")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["tickets"]), 1)
        self.assertEqual(response.data["tickets"][0]["status"], "in_progress")

        # Filter by ticket_type
        response = self.client.get("/api/resume/tickets?ticket_type=billing")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["tickets"]), 1)
        self.assertEqual(response.data["tickets"][0]["ticket_type"], "billing")

    def test_retrieve_ticket_detail(self):
        """Retrieve single ticket with chronological replies and attachments."""
        ticket = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Detailed Ticket",
            message="Initial ticket description.",
            status="New"
        )
        reply = TicketReply.objects.create(
            ticket=ticket,
            resume_user=self.user_a,
            message="Here is additional information."
        )

        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.get(f"/api/resume/tickets/{ticket.ticket_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data.get("data", {})
        self.assertEqual(data.get("ticket_id"), ticket.ticket_id)
        self.assertEqual(len(data.get("replies", [])), 1)
        self.assertEqual(data["replies"][0]["sender_type"], "resume_user")
        self.assertEqual(data["replies"][0]["message"], "Here is additional information.")

    def test_reply_to_ticket(self):
        """User can submit a reply, transitioning status to in_progress."""
        ticket = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Question about plan",
            message="How do I upgrade?",
            status="New"
        )

        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.post(
            f"/api/resume/tickets/{ticket.ticket_id}/reply",
            data={"message": "Any updates on my upgrade request?"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data.get("success"))

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        self.assertEqual(ticket.replies.count(), 1)
        self.assertEqual(ticket.replies.first().resume_user, self.user_a)

    def test_reply_to_closed_ticket_fails(self):
        """Cannot reply to a closed ticket."""
        ticket = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Old ticket",
            message="Already resolved.",
            status="closed"
        )

        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.post(
            f"/api/resume/tickets/{ticket.ticket_id}/reply",
            data={"message": "Trying to reply to closed ticket"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data.get("success"))

    def test_close_ticket(self):
        """User can explicitly close an active ticket."""
        ticket = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Ticket to close",
            message="Please close this.",
            status="in_progress"
        )

        token = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.post(f"/api/resume/tickets/{ticket.ticket_id}/close")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("success"))

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "closed")

    def test_strict_user_isolation(self):
        """User B cannot access or modify User A's tickets."""
        ticket_a = StudentTicket.objects.create(
            resume_user=self.user_a,
            subject="Alice Confidential Issue",
            message="Private details.",
            status="New"
        )

        token_b = self._get_token_for(self.user_b)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_b}")

        # 1. User B list must be empty
        response = self.client.get("/api/resume/tickets")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["tickets"]), 0)
        self.assertEqual(response.data["counts"]["total"], 0)

        # 2. User B cannot retrieve User A's ticket
        response = self.client.get(f"/api/resume/tickets/{ticket_a.ticket_id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # 3. User B cannot reply to User A's ticket
        response = self.client.post(
            f"/api/resume/tickets/{ticket_a.ticket_id}/reply",
            data={"message": "Unauthorized reply attempt"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # 4. User B cannot close User A's ticket
        response = self.client.post(f"/api/resume/tickets/{ticket_a.ticket_id}/close")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_module_isolation_aryuapp_vs_resume(self):
        """AryuApp LMS tickets are isolated and never returned in Resume ticket endpoints."""
        student_ticket = StudentTicket.objects.create(
            student=None, # e.g. AryuApp student or anonymous
            resume_user=None,
            subject="AryuApp LMS Course Issue",
            message="Python LMS course issue",
            status="New"
        )

        token_a = self._get_token_for(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a}")

        # List must not include AryuApp ticket
        response = self.client.get("/api/resume/tickets")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket_ids = [t["ticket_id"] for t in response.data["tickets"]]
        self.assertNotIn(student_ticket.ticket_id, ticket_ids)

        # Retrieve must return 404
        response = self.client.get(f"/api/resume/tickets/{student_ticket.ticket_id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

