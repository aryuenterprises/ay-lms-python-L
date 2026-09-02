from datetime import time, datetime
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.tokens import RefreshToken

from aryuapp.models import Student, StudentCourse, Attendance
from courses.models import Course, CourseCategory
from batches.models import NewBatch, ClassSchedule


class AttendanceReportTestCase(TestCase):
    """
    Unit tests for GET /api/v1/reports/attendance endpoint.
    Tests pagination defaults, sorting, metric calculations (total_classes,
    attended_classes, not_attended_classes, attendance_percentage), s_no, and student_id.
    """

    def setUp(self):
        self.client = APIClient()

        # Category, Course, Batch
        self.category = CourseCategory.objects.create(category_name="Testing", is_archived=False)
        self.course = Course.objects.create(course_name="Selenium", course_category=self.category, is_archived=False)
        self.batch = NewBatch.objects.create(
            title="BATCH_A",
            course=self.course,
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            start_time="10:00:00",
            end_time="12:00:00",
            is_archived=False
        )

        # Student
        self.student = Student.objects.create(
            first_name="Ravi",
            last_name="Teja",
            email="ravi@example.com",
            contact_no="9988776655",
            registration_id="std_999",
            username="raviteja",
            password=make_password("password123"),
            converter="campaign"
        )
        StudentCourse.objects.create(student=self.student, course=self.course, batch=self.batch)

        # 2 Class Schedules conducted
        self.sched1 = ClassSchedule.objects.create(
            new_batch=self.batch,
            course=self.course,
            scheduled_date=timezone.now().date(),
            start_time=time(10, 0, 0),
            end_time=time(12, 0, 0),
            is_archived=False,
            is_class_cancelled=False
        )
        self.sched2 = ClassSchedule.objects.create(
            new_batch=self.batch,
            course=self.course,
            scheduled_date=timezone.now().date(),
            start_time=time(10, 0, 0),
            end_time=time(12, 0, 0),
            is_archived=False,
            is_class_cancelled=False
        )

        # 1 Attendance record marked PRESENT
        Attendance.objects.create(
            student=self.student,
            schedule_id=self.sched1,
            course=self.course,
            new_batch=self.batch,
            date=timezone.now(),
            status="PRESENT"
        )

        # Auth
        token = RefreshToken()
        token["user_id"] = self.student.student_id
        token["user_type"] = "admin"
        self.access_token = str(token.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_get_attendance_report_metrics(self):
        url = "/api/v1/reports/attendance"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        data = response.data["data"]
        self.assertGreaterEqual(len(data), 1)

        ravi_record = next(item for item in data if item["student_name"] == "Ravi Teja")
        self.assertEqual(ravi_record["s_no"], 1)
        self.assertEqual(ravi_record["student_id"], "std_999")
        self.assertEqual(ravi_record["total_classes"], 2)
        self.assertEqual(ravi_record["attended_classes"], 1)
        self.assertEqual(ravi_record["not_attended_classes"], 1)
        self.assertEqual(ravi_record["attendance_percentage"], 50.0)

    def test_attendance_report_search_filter(self):
        url = "/api/v1/reports/attendance?search=ravi@example.com"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["student_name"], "Ravi Teja")

    def test_attendance_report_inclusive_date_filtering(self):
        # Update student created_at timestamp to 2026-08-28 06:37:46 UTC
        created_time = timezone.make_aware(datetime(2026, 8, 28, 6, 37, 46))
        Student.objects.filter(pk=self.student.pk).update(created_at=created_time)

        # Query to_date=2026-08-28
        url = "/api/v1/reports/attendance?from_date=2026-08-24&to_date=2026-08-28"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["student_name"], "Ravi Teja")



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


class GoogleReviewTestCase(TestCase):
    """
    Unit tests for Google Review API:
    - GET /api/v1/reports/google-reviews
    - POST /api/v1/reports/google-reviews (Upsert)
    - PATCH /api/v1/reports/google-reviews/<id> (Update)
    - DELETE /api/v1/reports/google-reviews/<id> (Reset)
    """

    def setUp(self):
        self.client = APIClient()

        self.category = CourseCategory.objects.create(category_name="DevOps", is_archived=False)
        self.course = Course.objects.create(course_name="Docker", course_category=self.category, is_archived=False)
        self.batch = NewBatch.objects.create(
            title="BATCH_DEV",
            course=self.course,
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            start_time="10:00:00",
            end_time="12:00:00",
            is_archived=False
        )

        self.student = Student.objects.create(
            first_name="Anand",
            last_name="Verma",
            email="anand@example.com",
            contact_no="9876543210",
            registration_id="AYA0826066",
            username="anandverma",
            password=make_password("pass123"),
            converter="webinar"
        )
        StudentCourse.objects.create(student=self.student, course=self.course, batch=self.batch)

        token = RefreshToken()
        token["user_id"] = self.student.student_id
        token["user_type"] = "admin"
        self.access_token = str(token.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_get_google_reviews_list(self):
        url = "/api/v1/reports/google-reviews"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("data", response.data)
        self.assertIn("pagination", response.data)
        self.assertIn("filter_options", response.data)

    def test_post_upsert_google_review(self):
        url = "/api/v1/reports/google-reviews"
        payload = {
            "raw_student_id": self.student.student_id,
            "student_id": "AYA0826066",
            "course_id": self.course.course_id,
            "batch_id": self.batch.batch_id,
            "is_google_review": True,
            "review_date": "2026-09-02",
            "screenshot_url": "https://example.com/screenshot.png"
        }
        # First POST should Create (201 Created)
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["is_google_review"], True)

        # Second POST should Upsert / Update (200 OK)
        payload["review_date"] = "2026-09-03"
        response_update = self.client.post(url, data=payload, format="json")
        self.assertEqual(response_update.status_code, status.HTTP_200_OK)
        self.assertEqual(response_update.data["data"]["review_date"], "2026-09-03")

    def test_post_validation_mandatory_review_date(self):
        url = "/api/v1/reports/google-reviews"
        payload = {
            "raw_student_id": self.student.student_id,
            "course_id": self.course.course_id,
            "batch_id": self.batch.batch_id,
            "is_google_review": True
            # review_date missing!
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertFalse(response.data["success"])

    def test_patch_and_delete_google_review(self):
        # First create
        url_post = "/api/v1/reports/google-reviews"
        payload = {
            "raw_student_id": self.student.student_id,
            "course_id": self.course.course_id,
            "batch_id": self.batch.batch_id,
            "is_google_review": True,
            "review_date": "2026-09-02"
        }
        res_post = self.client.post(url_post, data=payload, format="json")
        review_id = res_post.data["data"]["id"]

        # PATCH update
        url_patch = f"/api/v1/reports/google-reviews/{review_id}"
        patch_payload = {
            "review_date": "2026-09-05",
            "screenshot_url": "https://example.com/updated_screenshot.png"
        }
        res_patch = self.client.patch(url_patch, data=patch_payload, format="json")
        self.assertEqual(res_patch.status_code, status.HTTP_200_OK)
        self.assertEqual(res_patch.data["data"]["review_date"], "2026-09-05")

        # DELETE reset
        url_delete = f"/api/v1/reports/google-reviews/{review_id}"
        res_delete = self.client.delete(url_delete)
        self.assertEqual(res_delete.status_code, status.HTTP_200_OK)
        self.assertTrue(res_delete.data["success"])

    def test_post_markdown_wrapped_screenshot_url(self):
        url = "/api/v1/reports/google-reviews"
        payload = {
            "student_id": "AYA0826066",
            "raw_student_id": self.student.student_id,
            "course_id": self.course.course_id,
            "batch_id": self.batch.batch_id,
            "is_google_review": True,
            "review_date": "2026-09-02",
            "screenshot_url": "[https://storage.googleapis.com/your-bucket/reviews/AYA0826066_review.png](https://storage.googleapis.com/your-bucket/reviews/AYA0826066_review.png)"
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["screenshot_url"],
            "https://aylms.aryuprojects.com/api/media/AYA0826066_review.png"
        )






