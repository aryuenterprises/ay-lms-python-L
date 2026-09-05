import hmac
import hashlib
import json
from unittest.mock import patch, MagicMock
import requests
from django.test import TransactionTestCase, Client, TestCase, override_settings
from django.urls import reverse
from django.core.cache import cache
from rest_framework.test import APIRequestFactory
from payments.models import PaymentGateway, PaymentTransaction
from ebook.models import Ebook, EbookRegistration
from ebook.views import EbookRegistrationViewSet

@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class EbookWebhookTestCase(TransactionTestCase):

    def setUp(self):
        cache.clear()
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
        self.secret = "EbookSecret456"
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_test_ebook_pub",
            secret_key="rzp_test_ebook_sec",
            webhook_secret=self.secret,
            is_archived=False
        )
        self.client = Client()
        self.webhook_url = reverse("ebook-razorpay-webhook")

        self.ebook = Ebook.objects.create(
            title="Test Ebook",
            price=299.00,
            is_paid=True,
            rating=5
        )

        self.registration = EbookRegistration.objects.create(
            ebook=self.ebook,
            name="Jane Doe",
            email="jane@example.com",
            phone="9123456789",
            is_paid=False
        )

        self.order_id = "order_ebook_888"
        self.txn = PaymentTransaction.objects.create(
            gateway=self.gateway,
            order_id=self.order_id,
            transaction_id="TXN_EBOOK_1",
            amount=299.00,
            currency="INR",
            payment_status="pending",
            ebookregistration=self.registration,
            metadata={
                "ebook_id": self.ebook.id,
                "registration_id": self.registration.id
            }
        )

    def test_ebook_webhook_missing_signature(self):
        response = self.client.post(
            self.webhook_url,
            data=json.dumps({"event": "payment.captured"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_ebook_webhook_invalid_signature(self):
        payload = json.dumps({"event": "payment.captured"}).encode("utf-8")
        response = self.client.post(
            self.webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="invalid_sig_xyz"
        )
        self.assertEqual(response.status_code, 400)

    def test_ebook_webhook_valid_signature_payment_captured(self):
        payload_dict = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_ebook_pay_999",
                        "order_id": self.order_id
                    }
                }
            }
        }
        raw_payload = json.dumps(payload_dict).encode("utf-8")
        computed_sig = hmac.new(
            self.secret.encode("utf-8"),
            raw_payload,
            hashlib.sha256
        ).hexdigest()

        response = self.client.post(
            self.webhook_url,
            data=raw_payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=computed_sig
        )
        self.assertEqual(response.status_code, 200)

        self.txn.refresh_from_db()
        self.assertIn(self.txn.payment_status, ["captured", "done"])
        self.assertEqual((self.txn.metadata or {}).get("razorpay_payment_id"), "pay_ebook_pay_999")

        self.registration.refresh_from_db()
        self.assertTrue(self.registration.is_paid)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class EbookRegistrationFlowTestCase(TransactionTestCase):

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.ebook_a = Ebook.objects.create(
            title="Python Mastery",
            slug="python-mastery",
            price=0.00,
            is_paid=False,
            rating=5
        )
        self.ebook_b = Ebook.objects.create(
            title="Django Advanced",
            slug="django-advanced",
            price=499.00,
            is_paid=True,
            rating=5
        )
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
        PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_test_key",
            secret_key="rzp_test_secret",
            webhook_secret="secret123",
            is_archived=False
        )

    def _setup_mock_rzp(self, mock_rzp):
        instance = mock_rzp.return_value
        instance.order.create.return_value = {"id": "order_mock_123456"}

    @patch("ebook.views.send_ebook_registration_email")
    def test_1_new_user_new_ebook_password_generation_and_hashing(self, mock_send_email):
        url = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        payload = {
            "name": "Alice Smith",
            "email": "alice@example.com",
            "phone": "9876543210"
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, 200)

        reg = EbookRegistration.objects.filter(email="alice@example.com", ebook=self.ebook_a).first()
        self.assertIsNotNone(reg)
        self.assertTrue(reg.password.startswith("pbkdf2_sha256$"))

        # Verify email was called and password was passed
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args
        raw_pwd = call_args.kwargs.get("password")
        self.assertIsNotNone(raw_pwd)
        self.assertTrue(reg.check_password(raw_pwd))

    @patch("razorpay.Client")
    @patch("ebook.views.send_ebook_registration_email")
    def test_2_existing_user_different_ebook_account_reuse(self, mock_send_email, mock_rzp):
        self._setup_mock_rzp(mock_rzp)
        # 1. Register for Ebook A
        url_a = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        self.client.post(url_a, data={"name": "Bob", "email": "bob@example.com", "phone": "9876543211"})
        reg_a = EbookRegistration.objects.get(email="bob@example.com", ebook=self.ebook_a)
        pwd_hash_a = reg_a.password

        # 2. Register for Ebook B (Different Ebook)
        url_b = reverse("ebook-register", kwargs={"slug": self.ebook_b.slug})
        resp_b = self.client.post(url_b, data={"name": "Bob", "email": "bob@example.com", "phone": "9876543211"})
        self.assertEqual(resp_b.status_code, 200)

        reg_b = EbookRegistration.objects.get(email="bob@example.com", ebook=self.ebook_b)
        self.assertEqual(reg_b.password, pwd_hash_a)
        self.assertNotEqual(reg_a.id, reg_b.id)

    def test_3_existing_user_same_ebook_duplicate_prevention(self):
        url = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        payload = {"name": "Charlie", "email": "charlie@example.com", "phone": "9876543212"}
        self.client.post(url, data=payload)

        # Second attempt for same ebook
        resp2 = self.client.post(url, data=payload)
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("Already registered", resp2.json().get("message", ""))

    @patch("razorpay.Client")
    def test_4_existing_phone_different_ebook(self, mock_rzp):
        self._setup_mock_rzp(mock_rzp)
        url_a = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        self.client.post(url_a, data={"name": "Dave", "email": "dave1@example.com", "phone": "9111111111"})

        url_b = reverse("ebook-register", kwargs={"slug": self.ebook_b.slug})
        resp = self.client.post(url_b, data={"name": "Dave", "email": "dave2@example.com", "phone": "9111111111"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(EbookRegistration.objects.filter(phone="9111111111").count(), 2)

    @patch("razorpay.Client")
    def test_5_new_email_existing_phone_identity_resolution(self, mock_rzp):
        self._setup_mock_rzp(mock_rzp)
        url_a = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        self.client.post(url_a, data={"name": "Eve", "email": "eve@example.com", "phone": "9222222222"})
        reg_a = EbookRegistration.objects.get(phone="9222222222")

        url_b = reverse("ebook-register", kwargs={"slug": self.ebook_b.slug})
        resp = self.client.post(url_b, data={"name": "Eve New", "email": "eve_new@example.com", "phone": "9222222222"})
        self.assertEqual(resp.status_code, 200)
        reg_b = EbookRegistration.objects.get(ebook=self.ebook_b)
        self.assertEqual(reg_b.password, reg_a.password)

    @patch("ebook.views.send_ebook_registration_email")
    def test_6_password_hashing_check(self, mock_send_email):
        url = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        self.client.post(url, data={"name": "Frank", "email": "frank@example.com", "phone": "9333333333"})
        reg = EbookRegistration.objects.get(email="frank@example.com")

        raw_pwd = mock_send_email.call_args.kwargs.get("password")
        self.assertNotEqual(reg.password, raw_pwd)
        self.assertTrue(reg.check_password(raw_pwd))

    @patch("razorpay.Client")
    @patch("ebook.views.send_ebook_registration_email")
    def test_7_email_context_new_vs_existing_user(self, mock_send_email, mock_rzp):
        self._setup_mock_rzp(mock_rzp)
        # 1. New user -> gets password
        url_a = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        self.client.post(url_a, data={"name": "Grace", "email": "grace@example.com", "phone": "9444444444"})
        self.assertIsNotNone(mock_send_email.call_args.kwargs.get("password"))

        mock_send_email.reset_mock()

        # 2. Existing user -> password is None
        url_b = reverse("ebook-register", kwargs={"slug": self.ebook_b.slug})
        self.client.post(url_b, data={"name": "Grace", "email": "grace@example.com", "phone": "9444444444"})

        from ebook.views import EbookRegistrationViewSet
        reg_b = EbookRegistration.objects.get(email="grace@example.com", ebook=self.ebook_b)
        txn = PaymentTransaction.objects.get(ebookregistration=reg_b)
        EbookRegistrationViewSet.update_registration_after_payment(txn)

        self.assertIsNone(mock_send_email.call_args.kwargs.get("password"))

    @patch("razorpay.Client")
    def test_8_existing_user_password_preservation(self, mock_rzp):
        self._setup_mock_rzp(mock_rzp)
        url_a = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        self.client.post(url_a, data={"name": "Hank", "email": "hank@example.com", "phone": "9555555555"})
        reg_a_before = EbookRegistration.objects.get(email="hank@example.com")

        url_b = reverse("ebook-register", kwargs={"slug": self.ebook_b.slug})
        self.client.post(url_b, data={"name": "Hank", "email": "hank@example.com", "phone": "9555555555"})

        reg_a_after = EbookRegistration.objects.get(id=reg_a_before.id)
        self.assertEqual(reg_a_before.password, reg_a_after.password)

    def test_9_concurrent_duplicate_registration_prevention(self):
        url = reverse("ebook-register", kwargs={"slug": self.ebook_a.slug})
        payload = {"name": "Ivy", "email": "ivy@example.com", "phone": "9666666666"}

        resp1 = self.client.post(url, data=payload)
        resp2 = self.client.post(url, data=payload)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(EbookRegistration.objects.filter(email="ivy@example.com", ebook=self.ebook_a).count(), 1)

    def test_10_ebook_registration_email_design_for_new_user_with_credentials(self):
        """
        Verify Ebook registration success email uses Resume-style template with credentials.
        """
        from django.core import mail
        from ebook.ebook_emails import send_ebook_registration_email

        reg = EbookRegistration.objects.create(
            ebook=self.ebook_a,
            name="Julia Roberts",
            email="julia@example.com",
            phone="9777777777",
            is_paid=True,
        )

        send_ebook_registration_email(reg, password="JuliaSecurePass123!")

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]

        self.assertIn("Ebook Registration Successful", sent_email.subject)
        self.assertEqual(sent_email.to, ["julia@example.com"])

        # Check HTML alternative
        self.assertEqual(len(sent_email.alternatives), 1)
        html_content, mimetype = sent_email.alternatives[0]
        self.assertEqual(mimetype, "text/html")

        # Verify brand design matches Resume registration design
        self.assertIn("background-color: #f5f3ff;", html_content)
        self.assertIn("Ebook Registration Successful", html_content)
        self.assertIn("Julia Roberts", html_content)
        self.assertIn("JuliaSecurePass123!", html_content)
        self.assertIn("Your Account Login Credentials", html_content)
        self.assertIn(self.ebook_a.title, html_content)
        self.assertIn("Product of", html_content)
        self.assertIn("Aryu Academy Pvt.", html_content)

        # Verify no Resume-specific text leaked
        self.assertNotIn("PassATS account", html_content)
        self.assertNotIn("Verify Email Address", html_content)

    def test_11_ebook_registration_email_design_for_existing_user(self):
        """
        Verify Ebook registration success email uses Resume-style template for existing user without password.
        """
        from django.core import mail
        from ebook.ebook_emails import send_ebook_registration_email

        reg = EbookRegistration.objects.create(
            ebook=self.ebook_b,
            name="Kevin Bacon",
            email="kevin@example.com",
            phone="9888888888",
            is_paid=True,
        )

        send_ebook_registration_email(reg, password=None)

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]

        html_content, mimetype = sent_email.alternatives[0]
        self.assertIn("Ebook Registration Successful", html_content)
        self.assertIn("Kevin Bacon", html_content)
        self.assertIn("Registration Details", html_content)
        self.assertNotIn("Your Account Login Credentials", html_content)
        self.assertIn(self.ebook_b.title, html_content)


@override_settings(
    CLOUDFLARE_TURNSTILE_SECRET_KEY="test-secret-key",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class EbookTurnstileTestCase(TestCase):
    """
    Tests for Cloudflare Turnstile CAPTCHA in the Ebook registration API.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = EbookRegistrationViewSet.as_view({"post": "create"})
        self.ebook = Ebook.objects.create(
            title="Python Mastery",
            slug="python-mastery",
            price=0.00,
            is_paid=False,
            rating=5,
        )

    @patch("ebook.views.send_ebook_registration_email")
    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_success_registration_succeeds(self, mock_cf_post, mock_email):
        # 1. captcha_token supplied + Cloudflare success -> registration succeeds
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Alice Captcha",
                "email": "alice_cf@example.com",
                "phone": "9876543201",
                "captcha_token": "valid-turnstile-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        self.assertEqual(response.data.get("message"), "Registered successfully")
        mock_cf_post.assert_called_once()
        self.assertTrue(EbookRegistration.objects.filter(phone="9876543201").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_invalid_captcha_registration_rejected(self, mock_cf_post):
        # 2. captcha_token supplied + invalid CAPTCHA -> registration rejected
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error-codes": ["invalid-input-response"],
        }
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Bad Token User",
                "email": "bad_token@example.com",
                "phone": "9876543202",
                "captcha_token": "invalid-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("verification failed", response.data.get("message", "").lower())
        self.assertFalse(EbookRegistration.objects.filter(phone="9876543202").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_expired_invalid_token_registration_rejected(self, mock_cf_post):
        # 3. captcha_token supplied + expired/invalid token -> registration rejected
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error-codes": ["timeout-or-duplicate"],
        }
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Expired User",
                "email": "expired@example.com",
                "phone": "9876543203",
                "captcha_token": "expired-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertFalse(EbookRegistration.objects.filter(phone="9876543203").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_timeout_registration_rejected(self, mock_cf_post):
        # 4. captcha_token supplied + Cloudflare timeout -> registration rejected
        mock_cf_post.side_effect = requests.Timeout("Connection timed out")

        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Timeout User",
                "email": "timeout@example.com",
                "phone": "9876543204",
                "captcha_token": "timeout-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("unavailable", response.data.get("message", "").lower())
        self.assertFalse(EbookRegistration.objects.filter(phone="9876543204").exists())

    @patch("requests.post")
    def test_captcha_token_supplied_cloudflare_network_error_registration_rejected(self, mock_cf_post):
        # 5. captcha_token supplied + Cloudflare/network error -> registration rejected
        mock_cf_post.side_effect = requests.ConnectionError("Network error")

        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Net Error User",
                "email": "neterr@example.com",
                "phone": "9876543205",
                "captcha_token": "neterr-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))
        self.assertIn("unavailable", response.data.get("message", "").lower())
        self.assertFalse(EbookRegistration.objects.filter(phone="9876543205").exists())

    @patch("ebook.views.send_ebook_registration_email")
    @patch("requests.post")
    def test_no_captcha_token_existing_registration_behavior_unchanged(self, mock_cf_post, mock_email):
        # 6. No captcha_token -> existing registration behavior remains unchanged
        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "No Captcha User",
                "email": "nocaptcha@example.com",
                "phone": "9876543206",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        mock_cf_post.assert_not_called()
        self.assertTrue(EbookRegistration.objects.filter(phone="9876543206").exists())

    @patch("ebook.views.send_ebook_registration_email")
    @patch("requests.post")
    def test_captcha_token_is_not_persisted_in_ebook_registration(self, mock_cf_post, mock_email):
        # 7. CAPTCHA token is not persisted
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Persist Check User",
                "email": "persist@example.com",
                "phone": "9876543207",
                "captcha_token": "should-not-be-in-db-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 200)
        reg = EbookRegistration.objects.get(phone="9876543207")
        self.assertFalse(hasattr(reg, "captcha_token"))

    @patch("ebook.views.send_ebook_registration_email")
    @patch("requests.post")
    def test_captcha_token_is_not_returned_in_api_response(self, mock_cf_post, mock_email):
        # 8. CAPTCHA token is not returned in API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_cf_post.return_value = mock_response

        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Response Check User",
                "email": "resp@example.com",
                "phone": "9876543208",
                "captcha_token": "secret-captcha-token",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("captcha_token", response.data)
        self.assertNotIn("captcha_token", response.data.get("data", {}))

    def test_existing_validation_still_works_missing_email_and_phone(self):
        # 9. Existing validation still works (missing both email and phone rejected)
        request = self.factory.post(
            f"/{self.ebook.slug}/register/",
            data={
                "name": "Incomplete User",
            },
            format="json",
        )
        response = self.view(request, slug=self.ebook.slug)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Email or Phone is required", response.data.get("message", ""))

