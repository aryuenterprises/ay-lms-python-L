"""
Tests for Coding Assessment listing, detail, and student progress summaries.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from aryuapp.models import Student
from ..models import (
    CodingProblem,
    CodingAssessment,
    AssessmentProblem,
    CodeSubmission,
    AssessmentAttempt,
)
from ..constants import (
    DIFFICULTY_EASY,
    DIFFICULTY_MEDIUM,
    LANGUAGE_PYTHON,
    STATUS_ACCEPTED,
)

User = get_user_model()


def create_test_student(first_name="Bob", last_name="Student", email="bob@aryu.com", username="student_bob"):
    student = Student.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        username=username,
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


class AssessmentAPITestCase(TestCase):
    """
    Tests assessment browsing and student aggregate score summaries with Student model.
    """

    def setUp(self):
        self.client = APIClient()
        self.student, self.user = create_test_student()
        self.client.force_authenticate(user=self.user)

        self.prob1 = CodingProblem.objects.create(
            title="Problem One",
            difficulty=DIFFICULTY_EASY,
            supported_languages=[LANGUAGE_PYTHON],
            is_active=True,
        )
        self.prob2 = CodingProblem.objects.create(
            title="Problem Two",
            difficulty=DIFFICULTY_MEDIUM,
            supported_languages=[LANGUAGE_PYTHON],
            is_active=True,
        )

        self.assessment = CodingAssessment.objects.create(
            title="Midterm Coding Exam",
            duration_minutes=120,
            passing_percentage=60.00,
            is_active=True,
        )

        AssessmentProblem.objects.create(
            assessment=self.assessment,
            problem=self.prob1,
            order=1,
            points=50,
        )
        AssessmentProblem.objects.create(
            assessment=self.assessment,
            problem=self.prob2,
            order=2,
            points=50,
        )

    def test_list_assessments(self):
        """Verify listing active assessments."""
        response = self.client.get("/api/code-assessment/assessments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)

    def test_student_assessment_summary_progress(self):
        """Verify student progress and score aggregation on assessment."""
        # Create an accepted submission for problem 1 (100% of 50 pts = 50 pts)
        CodeSubmission.objects.create(
            student=self.student,
            problem=self.prob1,
            assessment=self.assessment,
            language=LANGUAGE_PYTHON,
            source_code="print('ok')",
            status=STATUS_ACCEPTED,
            score=100.00,
        )

        response = self.client.get(f"/api/code-assessment/assessments/{self.assessment.slug}/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_problems"], 2)
        self.assertEqual(response.data["problems_attempted"], 1)
        self.assertEqual(response.data["earned_points"], 50.0)
        self.assertEqual(response.data["student_id"], self.student.student_id)

        # Confirm AssessmentAttempt record was created/updated
        attempt = AssessmentAttempt.objects.filter(student=self.student, assessment=self.assessment).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(float(attempt.score), 50.0)
