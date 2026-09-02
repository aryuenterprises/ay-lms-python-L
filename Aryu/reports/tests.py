from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.tokens import RefreshToken

from aryuapp.models import Student, StudentCourse
from courses.models import Course, CourseCategory
from batches.models import NewBatch


class StudentEnrollmentReportTestCase(TestCase):
    """
    Unit tests for /api/reports/student-enrollments endpoint.
    Tests pagination, searching, date filtering, sorting, batch hyphen fallback,
    and action context (student_id).
    """

    def setUp(self):
        self.client = APIClient()

        # Create Course Category
        self.category = CourseCategory.objects.create(
            category_name="Programming",
            is_archived=False
        )

        # Create Courses
        self.course1 = Course.objects.create(
            course_name="AI Python",
            course_category=self.category,
            fee=5000,
            duration="3",
            duration_type="Months",
            is_archived=False
        )
        self.course2 = Course.objects.create(
            course_name="Full Stack Dev",
            course_category=self.category,
            fee=8000,
            duration="6",
            duration_type="Months",
            is_archived=False
        )

        # Create Batches
        self.batch1 = NewBatch.objects.create(
            title="MORNING",
            course=self.course1,
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            start_time="09:00:00",
            end_time="11:00:00",
            is_archived=False
        )

        # Create Students
        now = timezone.now()
        self.student1 = Student.objects.create(
            first_name="Ram",
            last_name="Kumar",
            email="ram@example.com",
            contact_no="9876543210",
            registration_id="std_123",
            username="ram123",
            password=make_password("password123"),
            city="Chennai",
            state="TN",
            country="India",
            converter="campaign",
        )
        Student.objects.filter(pk=self.student1.pk).update(created_at=now - timezone.timedelta(days=10))
        self.student1.refresh_from_db()

        # Enroll Student 1 into Course 1 & Batch 1
        StudentCourse.objects.create(
            student=self.student1,
            course=self.course1,
            batch=self.batch1
        )

        self.student2 = Student.objects.create(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            contact_no="9876543211",
            registration_id="std_124",
            username="johndoe",
            password=make_password("password123"),
            city="Bangalore",
            state="KA",
            country="India",
            converter="public",
        )
        Student.objects.filter(pk=self.student2.pk).update(created_at=now - timezone.timedelta(days=5))
        self.student2.refresh_from_db()

        # Enroll Student 2 into Course 2 without batch
        StudentCourse.objects.create(
            student=self.student2,
            course=self.course2,
            batch=self.batch1  # will test hyphen fallback separately
        )

        self.student3 = Student.objects.create(
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
            contact_no="9876543212",
            registration_id="std_125",
            username="alicesmith",
            password=make_password("password123"),
            city="Delhi",
            state="DL",
            country="India",
            converter="campaign",
        )
        Student.objects.filter(pk=self.student3.pk).update(created_at=now - timezone.timedelta(days=1))
        self.student3.refresh_from_db()
        # Student 3 has no course and no batch assigned (tests batch & course "-" fallback)

        # JWT Token for API Client
        token = RefreshToken()
        token["user_id"] = self.student1.student_id
        token["user_type"] = "admin"
        self.access_token = str(token.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_get_student_enrollments_default_pagination(self):
        url = "/api/reports/student-enrollments"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        pagination = response.data["pagination"]
        self.assertEqual(pagination["total_count"], 3)
        self.assertEqual(pagination["page"], 1)
        self.assertEqual(pagination["limit"], 50)
        self.assertEqual(pagination["total_pages"], 1)

        data = response.data["data"]
        self.assertEqual(len(data), 3)

    def test_get_student_enrollments_custom_limit_and_page(self):
        url = "/api/reports/student-enrollments?page=1&limit=2"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["pagination"]["total_count"], 3)
        self.assertEqual(response.data["pagination"]["total_pages"], 2)
        self.assertEqual(len(response.data["data"]), 2)

    def test_search_filter_by_student_name(self):
        url = "/api/reports/student-enrollments?search=Ram"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["student_name"], "Ram Kumar")
        self.assertEqual(data[0]["student_id"], "std_123")

    def test_search_filter_by_course_name(self):
        url = "/api/reports/student-enrollments?search=AI Python"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["course"], "AI Python")

    def test_batch_and_course_hyphen_fallback(self):
        url = f"/api/reports/student-enrollments?search=Alice"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data), 1)
        record = data[0]
        self.assertEqual(record["student_name"], "Alice Smith")
        self.assertEqual(record["batch"], "-")
        self.assertEqual(record["course"], "-")

    def test_sorting_by_name(self):
        url = "/api/reports/student-enrollments?sort_by=first_name&sort_order=asc"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        names = [d["student_name"] for d in data]
        self.assertEqual(names, ["Alice Smith", "John Doe", "Ram Kumar"])

    def test_date_filtering(self):
        # Filter for last 3 days
        from_date = (timezone.now() - timezone.timedelta(days=3)).strftime("%Y-%m-%d")
        url = f"/api/reports/student-enrollments?from_date={from_date}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["student_name"], "Alice Smith")

    def test_course_id_and_batch_id_filtering(self):
        url = f"/api/reports/student-enrollments?course_id={self.course1.course_id}&batch_id={self.batch1.batch_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["student_name"], "Ram Kumar")
        self.assertEqual(data[0]["course_id"], self.course1.course_id)
        self.assertEqual(data[0]["batch_id"], self.batch1.batch_id)

    def test_filter_options_in_response(self):
        url = "/api/reports/student-enrollments"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("filter_options", response.data)
        filter_options = response.data["filter_options"]
        self.assertIn("courses", filter_options)
        self.assertIn("batches", filter_options)
        self.assertGreaterEqual(len(filter_options["courses"]), 2)
        self.assertGreaterEqual(len(filter_options["batches"]), 1)
        self.assertEqual(filter_options["batches"][0]["course_id"], self.course1.course_id)

    def test_dynamic_batches_filter_options_and_batch_id_reset(self):
        # Create a second batch for course 2
        batch2 = NewBatch.objects.create(
            title="EVENING",
            course=self.course2,
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            start_time="17:00:00",
            end_time="19:00:00",
            is_archived=False
        )

        # 1. When course_id=self.course1.course_id is passed, filter_options.batches should only return batches for course1
        url = f"/api/reports/student-enrollments?course_id={self.course1.course_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        filter_options = response.data["filter_options"]
        batch_course_ids = [b["course_id"] for b in filter_options["batches"]]
        self.assertTrue(all(cid == self.course1.course_id for cid in batch_course_ids))

        # 2. When batch_id does not belong to course_id (e.g. course1 with batch2 of course2), batch_id filter should be discarded
        url_mismatch = f"/api/reports/student-enrollments?course_id={self.course1.course_id}&batch_id={batch2.batch_id}"
        response_mismatch = self.client.get(url_mismatch)
        self.assertEqual(response_mismatch.status_code, status.HTTP_200_OK)
        # Should still return Ram Kumar (who is enrolled in course 1), rather than empty list from invalid batch filter
        self.assertGreaterEqual(len(response_mismatch.data["data"]), 1)




