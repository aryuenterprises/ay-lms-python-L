from django.test import TestCase
from django.core import mail
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from aryuapp.models import Certificate, Student
from aryuapp.certificate_filler import generate_and_send_certificate_pdf
from aryuapp.views import send_certificate_email

User = get_user_model()


class CertificateIntegrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="adminuser",
            email="admin@aryuacademy.com",
            password="TestPassword@123",
            user_type="admin"
        )
        self.client.force_authenticate(user=self.user)

        self.student = Student.objects.create(
            first_name="John",
            last_name="Doe",
            username="johndoe",
            email="john.doe@example.com",
            contact_no="9876543210",
            current_address="123 Main St",
            permanent_address="123 Main St",
            city="Chennai",
            state="Tamil Nadu",
            country="India",
            converter="Self",
            status=True
        )

    def test_certificate_pdf_generation(self):
        """Test certificate image and PDF generation saves file to model."""
        certificate = Certificate.objects.create(
            student=self.student,
            student_name=f"{self.student.first_name} {self.student.last_name}",
            course_name="Full Stack Python",
            course_duration="3 Months"
        )
        pdf_path = generate_and_send_certificate_pdf(certificate)
        certificate.refresh_from_db()

        self.assertTrue(bool(certificate.certificate_file))
        self.assertTrue(certificate.certificate_file.name.endswith(".pdf"))

    def test_send_certificate_email(self):
        """Test sending certificate email with PDF attachment."""
        certificate = Certificate.objects.create(
            student=self.student,
            student_name=f"{self.student.first_name} {self.student.last_name}",
            course_name="Full Stack Python",
            course_duration="3 Months"
        )
        generate_and_send_certificate_pdf(certificate)
        certificate.refresh_from_db()

        mail.outbox.clear()
        sent = send_certificate_email(self.student.email, certificate)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertIn("Full Stack Python", email.subject)
        self.assertEqual(email.to, [self.student.email])
        self.assertTrue(len(email.attachments) >= 1)

    def test_certificate_api_create_flow(self):
        """Test full API call -> certificate generation -> email sending."""
        mail.outbox.clear()
        payload = {
            "student": self.student.student_id,
            "student_name": "John Doe",
            "course_name": "Data Science & AI",
            "course_duration": "6 Months",
            "organization_name": "Aryu Academy",
            "notes": "Grade A+"
        }

        response = self.client.post("/api/certificate", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data.get("success"))

        cert_id = response.data["data"]["id"]
        certificate = Certificate.objects.get(id=cert_id)
        self.assertTrue(bool(certificate.certificate_file))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.student.email])

    def test_certificate_api_duplicate_prevention(self):
        """Test duplicate certificate creation avoids re-sending duplicate emails."""
        payload = {
            "student": self.student.student_id,
            "student_name": "John Doe",
            "course_name": "Data Science & AI",
            "course_duration": "6 Months"
        }

        # First request
        resp1 = self.client.post("/api/certificate", payload, format="json")
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)

        # Retry request for the same student and course
        resp2 = self.client.post("/api/certificate", payload, format="json")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertIn("already exists", resp2.data.get("message", ""))
        # Email count should remain 1 (no duplicate sent)
        self.assertEqual(len(mail.outbox), 1)