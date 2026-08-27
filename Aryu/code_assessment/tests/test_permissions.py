"""
Permissions and IDOR protection tests using existing aryuapp.Student model.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from aryuapp.models import Student
from ..models import (
    CodingProblem,
    CodeSubmission,
)
from ..constants import (
    DIFFICULTY_EASY,
    LANGUAGE_PYTHON,
    STATUS_ACCEPTED,
)

User = get_user_model()


def create_student(username, email, first_name):
    student = Student.objects.create(
        username=username,
        email=email,
        first_name=first_name,
        last_name="Test",
        contact_no="9876543210",
        current_address="123 Test St",
        permanent_address="123 Test St",
        city="Chennai",
        state="Tamil Nadu",
        country="India",
        converter="test",
    )
    user = User.objects.create_user(
        username=username,
        email=email,
        password="Password123!",
    )
    return student, user


class CodeAssessmentPermissionsTestCase(TestCase):
    """
    Tests IDOR defenses, student isolation, and admin role restrictions with Student model.
    """

    def setUp(self):
        self.student_a, self.user_a = create_student("student_a", "student_a@aryu.com", "StudentA")
        self.student_b, self.user_b = create_student("student_b", "student_b@aryu.com", "StudentB")

        self.staff_admin = User.objects.create_superuser(
            username="staff_admin",
            email="admin@aryu.com",
            password="AdminPassword123!",
        )

        self.problem = CodingProblem.objects.create(
            title="IDOR Test Problem",
            difficulty=DIFFICULTY_EASY,
            supported_languages=[LANGUAGE_PYTHON],
            is_active=True,
        )

        # Submission belonging to Student A
        self.sub_a = CodeSubmission.objects.create(
            student=self.student_a,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="print('student A solution')",
            status=STATUS_ACCEPTED,
            score=100.00,
        )

    def test_idor_student_b_cannot_access_student_a_submission(self):
        """CRITICAL: Student B must NOT be able to view Student A's submission."""
        client = APIClient()
        client.force_authenticate(user=self.user_b)

        # Attempt to retrieve Student A's submission directly by ID
        response = client.get(f"/api/code-assessment/submissions/{self.sub_a.id}/")
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

        # Attempt to access result endpoint directly
        result_resp = client.get(f"/api/code-assessment/submissions/{self.sub_a.id}/result/")
        self.assertIn(result_resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_student_a_can_access_own_submission(self):
        """Verify Student A can access their own submission."""
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        response = client.get(f"/api/code-assessment/submissions/{self.sub_a.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.sub_a.id)
        self.assertEqual(response.data["student_id"], self.student_a.student_id)

    def test_student_a_submission_list_only_contains_own_submissions(self):
        """Verify GET /submissions/ returns only Student A's submissions and not Student B's."""
        # Create submission for Student B
        CodeSubmission.objects.create(
            student=self.student_b,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="print('student B solution')",
            status=STATUS_ACCEPTED,
        )

        client = APIClient()
        client.force_authenticate(user=self.user_a)

        response = client.get("/api/code-assessment/submissions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.sub_a.id)

    def test_client_cannot_spoof_student_id_in_submission_request(self):
        """Verify backend ignores any client-supplied student_id and uses authenticated Student."""
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        payload = {
            "problem_id": self.problem.id,
            "language": LANGUAGE_PYTHON,
            "source_code": "print('TWO_SUM')",
            "student_id": self.student_b.student_id,  # Malicious attempt to spoof Student B
        }

        response = client.post(
            f"/api/code-assessment/problems/{self.problem.slug}/submit/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        sub_id = response.data["submission_id"]
        sub = CodeSubmission.objects.get(pk=sub_id)

        # Submission MUST belong to Student A (authenticated requester), NOT spoofed Student B
        self.assertEqual(sub.student, self.student_a)
        self.assertNotEqual(sub.student, self.student_b)

    def test_staff_admin_can_access_any_submission(self):
        """Verify Staff/Admin can view any submission for grading/review."""
        client = APIClient()
        client.force_authenticate(user=self.staff_admin)

        response = client.get(f"/api/code-assessment/submissions/{self.sub_a.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_student_cannot_access_admin_endpoints(self):
        """Verify normal students receive 403 Forbidden on administrative CRUD APIs."""
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        response = client.get("/api/code-assessment/admin/problems/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
