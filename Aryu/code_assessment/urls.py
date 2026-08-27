"""
URLconf for Code Assessment module.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProblemViewSet,
    SubmissionViewSet,
    AssessmentViewSet,
    AdminProblemViewSet,
    AdminTestCaseViewSet,
    AdminAssessmentViewSet,
)

router = DefaultRouter()
router.register(r"problems", ProblemViewSet, basename="coding-problem")
router.register(r"submissions", SubmissionViewSet, basename="code-submission")
router.register(r"assessments", AssessmentViewSet, basename="coding-assessment")

# Admin routes
router.register(r"admin/problems", AdminProblemViewSet, basename="admin-coding-problem")
router.register(r"admin/test-cases", AdminTestCaseViewSet, basename="admin-test-case")
router.register(r"admin/assessments", AdminAssessmentViewSet, basename="admin-coding-assessment")

urlpatterns = [
    path("", include(router.urls)),
]
