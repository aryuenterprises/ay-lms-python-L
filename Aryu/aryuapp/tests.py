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

    def test_student_certificate_status_no_certificate_no_review(self):
        """Test status endpoint when student has no certificate and no google review."""
        response = self.client.get(f"/api/certificates/student-status/{self.student.student_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("success"))
        data = response.data["data"]
        self.assertEqual(data["student_name"], "John Doe")
        self.assertEqual(data["google_review"], "no")
        self.assertFalse(data["has_google_review"])
        self.assertEqual(data["certificate_sent"], "no")
        self.assertFalse(data["has_certificate"])
        self.assertIsNone(data["file_path"])
        self.assertIsNone(data["file_url"])

    def test_student_certificate_status_with_certificate_and_google_review(self):
        """Test status endpoint with certificate file and Google review."""
        from reports.models import GoogleReview

        # Create google review
        GoogleReview.objects.create(
            student=self.student,
            is_google_review=True
        )

        # Create certificate with PDF file
        certificate = Certificate.objects.create(
            student=self.student,
            student_name=f"{self.student.first_name} {self.student.last_name}",
            course_name="Full Stack Python",
            course_duration="3 Months"
        )
        generate_and_send_certificate_pdf(certificate)
        certificate.refresh_from_db()

        # Query using numeric student_id
        response = self.client.get(f"/api/certificates/student-status/{self.student.student_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("success"))
        data = response.data["data"]
        self.assertEqual(data["student_name"], "John Doe")
        self.assertEqual(data["course_duration"], "3 Months")
        self.assertEqual(data["google_review"], "yes")
        self.assertTrue(data["has_google_review"])
        self.assertIn("review_links", data)
        self.assertIn("google_review_screenshot", data)
        self.assertEqual(data["certificate_sent"], "yes")
        self.assertTrue(data["has_certificate"])
        self.assertIsNotNone(data["file_path"])
        self.assertTrue(data["file_path"].endswith(".pdf"))
        self.assertEqual(len(data["certificates"]), 1)
        self.assertEqual(data["certificates"][0]["certificate_sent"], "yes")

        # Query using registration_id via alternative path
        reg_response = self.client.get(f"/api/student-certificate-status/{self.student.registration_id}")
        self.assertEqual(reg_response.status_code, status.HTTP_200_OK)
        self.assertEqual(reg_response.data["data"]["student_id"], self.student.student_id)
        self.assertEqual(reg_response.data["data"]["course_duration"], "3 Months")

        # Query using query parameter ?student_id=...
        param_response = self.client.get(f"/api/certificates/student-status?student_id={self.student.student_id}")
        self.assertEqual(param_response.status_code, status.HTTP_200_OK)
        self.assertEqual(param_response.data["data"]["student_id"], self.student.student_id)
        self.assertEqual(param_response.data["data"]["course_duration"], "3 Months")

    def test_student_certificate_status_not_found(self):
        """Test status endpoint with invalid student id returns 404."""
        response = self.client.get("/api/certificates/student-status/999999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data.get("success"))

    def test_student_certificate_status_default_all_students(self):
        """Test default GET returns all students list when student_id is not provided."""
        # Create a second student
        Student.objects.create(
            first_name="Jane",
            last_name="Smith",
            username="janesmith",
            email="jane.smith@example.com",
            contact_no="9876543211",
            current_address="456 Elm St",
            permanent_address="456 Elm St",
            city="Chennai",
            state="Tamil Nadu",
            country="India",
            converter="Self",
            status=True
        )

        response = self.client.get("/api/certificates/student-status")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("success"))
        self.assertIsInstance(response.data["data"], list)
        self.assertGreaterEqual(len(response.data["data"]), 2)
        
        # Verify fields in list items
        first_item = response.data["data"][0]
        self.assertIn("student_id", first_item)
        self.assertIn("student_name", first_item)
        self.assertIn("course_duration", first_item)
        self.assertIn("google_review", first_item)
        self.assertIn("certificate_sent", first_item)
        self.assertIn("file_path", first_item)
        self.assertIn("certificates", first_item)
        self.assertIn("review_platforms", first_item)
        self.assertIn("reviews_links", first_item)
        self.assertIn("pagination", response.data)

    def test_student_certificate_status_pagination(self):
        """Test GET /api/certificates/student-status?page=1&limit=50 pagination structure."""
        response = self.client.get("/api/certificates/student-status?page=1&limit=50")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("success"))
        self.assertIn("pagination", response.data)
        pagination = response.data["pagination"]
        self.assertEqual(pagination["page"], 1)
        self.assertEqual(pagination["limit"], 50)
        self.assertIn("total_count", pagination)
        self.assertIn("total_pages", pagination)
        self.assertIsInstance(response.data["data"], list)

    def test_student_certificate_status_all_reviews_links(self):
        """Test that all review links (Google, Facebook, Trustpilot, YouTube, LinkedIn) are present."""
        from reports.models import GoogleReview

        # Create multi-platform review
        GoogleReview.objects.create(
            student=self.student,
            is_google_review=True,
            facebook_review=True,
            trustpilot_review=True,
            is_youtube_testimonial=True,
            youtube_testimonial_link="https://www.youtube.com/watch?v=example123",
            linkedin_review=True
        )

        # 1. Test single student status
        single_resp = self.client.get(f"/api/certificates/student-status/{self.student.student_id}")
        self.assertEqual(single_resp.status_code, status.HTTP_200_OK)
        single_data = single_resp.data["data"]

        self.assertTrue(single_data["is_google_review"])
        self.assertTrue(single_data["facebook_review"])
        self.assertTrue(single_data["trustpilot_review"])
        self.assertTrue(single_data["is_youtube_testimonial"])
        self.assertEqual(single_data["youtube_testimonial_link"], "https://www.youtube.com/watch?v=example123")
        self.assertTrue(single_data["linkedin_review"])

        self.assertIn("Google", single_data["review_platforms"])
        self.assertIn("Facebook", single_data["review_platforms"])
        self.assertIn("Trustpilot", single_data["review_platforms"])
        self.assertIn("YouTube", single_data["review_platforms"])
        self.assertIn("LinkedIn", single_data["review_platforms"])

        self.assertIsInstance(single_data["reviews_links"], list)
        platform_names = [r["platform"] for r in single_data["reviews_links"]]
        self.assertEqual(platform_names, ["Google", "Facebook", "Trustpilot", "YouTube", "LinkedIn"])

        # 2. Test list endpoint with page=1&limit=50
        list_resp = self.client.get("/api/certificates/student-status?page=1&limit=50")
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        items = list_resp.data["data"]
        matched = next((item for item in items if item["student_id"] == self.student.student_id), None)
        self.assertIsNotNone(matched)
        self.assertTrue(matched["is_google_review"])
        self.assertTrue(matched["facebook_review"])
        self.assertTrue(matched["trustpilot_review"])
        self.assertTrue(matched["is_youtube_testimonial"])
        self.assertEqual(matched["youtube_testimonial_link"], "https://www.youtube.com/watch?v=example123")
        self.assertTrue(matched["linkedin_review"])
        self.assertIn("Google", matched["review_platforms"])
        self.assertEqual(len(matched["reviews_links"]), 5)