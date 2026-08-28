import io
from PIL import Image
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Course, CourseCategory
from aryuapp.models import Trainer, ModulePermission, Role, RoleModulePermission


def generate_test_image(filename="test_thumb.png"):
    file_obj = io.BytesIO()
    image = Image.new("RGBA", size=(100, 100), color=(155, 0, 0, 255))
    image.save(file_obj, "png")
    file_obj.seek(0)
    return SimpleUploadedFile(filename, file_obj.read(), content_type="image/png")


class CourseSyllabusThumbnailTestCase(TestCase):
    """
    Test suite for Course syllabus thumbnail image support and URL generation.
    """

    def setUp(self):
        self.client = APIClient()

        # Create super_admin role
        self.role = Role.objects.create(
            name="super_admin"
        )

        # Create Course module permission
        self.course_module = ModulePermission.objects.create(
            module="Course",
            actions=["create", "read", "update", "delete"]
        )

        self.role_module_perm = RoleModulePermission.objects.create(
            role=self.role,
            module_permission=self.course_module,
            allowed_actions=["create", "read", "update", "delete"]
        )

        self.category = CourseCategory.objects.create(
            category_name="Engineering",
            is_archived=False
        )

        # Setup Super Admin / Trainer for authenticated CourseViewSet calls
        self.trainer = Trainer.objects.create(
            employee_id="EMP_TEST_001",
            full_name="Admin User",
            email="admin@aryuacademy.com",
            user_type="super_admin",
            role=self.role,
            contact_no="9876543210",
            status=True,
            is_archived=False
        )

        # Generate JWT token for super_admin
        refresh = RefreshToken()
        refresh["user_id"] = self.trainer.trainer_id
        refresh["trainer_id"] = self.trainer.trainer_id
        refresh["user_type"] = "super_admin"
        refresh["role_id"] = self.role.role_id
        self.token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_1_course_model_has_syllabus_thumbnail_field(self):
        """COURSE TEST 1: Verify Course model has syllabus_thumbnail field and it is optional."""
        field = Course._meta.get_field("syllabus_thumbnail")
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertEqual(field.upload_to, "course/syllabus_thumbnails/")

    def test_2_migration_applied(self):
        """COURSE TEST 2: Verify migration is applied."""
        course = Course.objects.create(
            course_name="Python Backend Mastery",
            course_category=self.category,
            status="Active"
        )
        self.assertFalse(bool(course.syllabus_thumbnail))

    def test_3_syllabus_thumbnail_upload_and_storage(self):
        """COURSE TEST 3: Create course with valid syllabus thumbnail and verify storage path."""
        thumb = generate_test_image("python_syllabus.png")
        pdf = SimpleUploadedFile("python_syllabus.pdf", b"%PDF-1.4 test content", content_type="application/pdf")

        course = Course.objects.create(
            course_name="Python Advanced",
            course_category=self.category,
            syllabus=pdf,
            syllabus_thumbnail=thumb,
            status="Active"
        )

        self.assertTrue(course.syllabus_thumbnail.name.startswith("course/syllabus_thumbnails/"))
        self.assertTrue(course.syllabus.name.startswith("syllabus/"))

    def test_4_syllabus_thumbnail_url_generation(self):
        """COURSE TEST 4: Verify API returns settings-based syllabus_thumbnail_url."""
        thumb = generate_test_image("thumb_sample.png")
        course = Course.objects.create(
            course_name="Django Web Development",
            course_category=self.category,
            syllabus_thumbnail=thumb,
            status="Active"
        )

        resp = self.client.get(f"/api/courses/{course.course_id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        expected_url = settings.MEDIA_BASE_URL + course.syllabus_thumbnail.url
        self.assertEqual(resp.data.get("syllabus_thumbnail_url"), expected_url)

    def test_5_existing_syllabus_pdf_url_unchanged(self):
        """COURSE TEST 5: Verify existing syllabus PDF URL remains completely intact."""
        pdf = SimpleUploadedFile("django_guide.pdf", b"%PDF-1.4 sample syllabus", content_type="application/pdf")
        course = Course.objects.create(
            course_name="Django Guide Course",
            course_category=self.category,
            syllabus=pdf,
            status="Active"
        )

        resp = self.client.get(f"/api/courses/{course.course_id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        expected_syllabus_url = settings.MEDIA_BASE_URL + course.syllabus.url
        self.assertEqual(resp.data.get("syllabus_url"), expected_syllabus_url)
        self.assertIsNone(resp.data.get("syllabus_thumbnail_url"))

    def test_6_missing_thumbnail_returns_none(self):
        """COURSE TEST 6: Missing thumbnail returns None without exception."""
        course = Course.objects.create(
            course_name="Empty Thumbnail Course",
            course_category=self.category,
            status="Active"
        )

        resp = self.client.get(f"/api/courses/{course.course_id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data.get("syllabus_thumbnail_url"))
        self.assertIsNone(resp.data.get("syllabus_url"))

    def test_7_course_api_round_trip(self):
        """COURSE TEST 7: Perform multipart create/patch -> GET course with thumbnail."""
        thumb = generate_test_image("roundtrip_thumb.png")
        pdf = SimpleUploadedFile("roundtrip_syllabus.pdf", b"%PDF-1.4 syllabus", content_type="application/pdf")

        create_payload = {
            "course_name": "Full Stack Mastery",
            "course_category": self.category.category_name,
            "syllabus": pdf,
            "syllabus_thumbnail": thumb,
            "status": "Active",
            "fee": 5000.00
        }

        create_resp = self.client.post(
            "/api/courses",
            data=create_payload,
            format="multipart"
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        course_data = create_resp.data.get("data", create_resp.data)
        course_id = course_data["course_id"]

        self.assertIsNotNone(course_data.get("syllabus_thumbnail_url"))
        self.assertIsNotNone(course_data.get("syllabus_url"))

        # Retrieve course
        get_resp = self.client.get(f"/api/courses/{course_id}")
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(get_resp.data["syllabus_thumbnail_url"], course_data["syllabus_thumbnail_url"])
        self.assertEqual(get_resp.data["syllabus_url"], course_data["syllabus_url"])

    @override_settings(MEDIA_BASE_URL="https://custom-cdn.aryuacademy.com")
    def test_8_settings_based_url_dynamic(self):
        """COURSE TEST 8: Verify dynamic base URL from settings is used."""
        thumb = generate_test_image("cdn_thumb.png")
        course = Course.objects.create(
            course_name="Cloud CDN Course",
            course_category=self.category,
            syllabus_thumbnail=thumb,
            status="Active"
        )

        resp = self.client.get(f"/api/courses/{course.course_id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["syllabus_thumbnail_url"].startswith("https://custom-cdn.aryuacademy.com/media/course/syllabus_thumbnails/"))
