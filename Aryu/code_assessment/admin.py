"""
Django admin registration for Code Assessment models.
Directly links to aryuapp.Student model.
"""
from django.contrib import admin
from .models import (
    CodingProblem,
    CodingTestCase,
    CodingAssessment,
    AssessmentProblem,
    AssessmentAttempt,
    CodeSubmission,
    SubmissionTestCaseResult,
)


class CodingTestCaseInline(admin.TabularInline):
    model = CodingTestCase
    extra = 1
    fields = ("order", "is_sample", "is_hidden", "input_data", "expected_output", "explanation")


@admin.register(CodingProblem)
class CodingProblemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "difficulty",
        "time_limit_ms",
        "memory_limit_mb",
        "is_active",
        "total_submissions_count",
        "accepted_submissions_count",
        "acceptance_rate",
        "created_at",
    )
    list_filter = ("difficulty", "is_active", "created_at")
    search_fields = ("title", "slug", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [CodingTestCaseInline]


@admin.register(CodingTestCase)
class CodingTestCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "problem", "is_sample", "is_hidden", "order", "created_at")
    list_filter = ("is_sample", "is_hidden", "problem")
    search_fields = ("problem__title", "input_data", "expected_output")


class AssessmentProblemInline(admin.TabularInline):
    model = AssessmentProblem
    extra = 1
    fields = ("order", "problem", "points")


@admin.register(CodingAssessment)
class CodingAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "course",
        "duration_minutes",
        "passing_percentage",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "course")
    search_fields = ("title", "slug", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [AssessmentProblemInline]


@admin.register(AssessmentAttempt)
class AssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "assessment",
        "score",
        "is_passed",
        "is_completed",
        "started_at",
        "completed_at",
    )
    list_filter = ("is_passed", "is_completed", "assessment")
    search_fields = ("student__first_name", "student__last_name", "student__email", "assessment__title")


class SubmissionTestCaseResultInline(admin.TabularInline):
    model = SubmissionTestCaseResult
    extra = 0
    readonly_fields = ("test_case", "status", "execution_time_ms", "memory_used_kb", "stdout", "stderr", "error_message")
    can_delete = False


@admin.register(CodeSubmission)
class CodeSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "problem",
        "assessment",
        "language",
        "status",
        "score",
        "passed_test_cases",
        "total_test_cases",
        "submitted_at",
    )
    list_filter = ("status", "language", "problem", "assessment")
    search_fields = ("student__first_name", "student__last_name", "student__email", "problem__title")
    readonly_fields = (
        "student",
        "problem",
        "assessment",
        "language",
        "source_code",
        "status",
        "score",
        "total_test_cases",
        "passed_test_cases",
        "execution_time_ms",
        "memory_used_kb",
        "error_message",
        "compile_output",
        "submitted_at",
        "completed_at",
    )
    inlines = [SubmissionTestCaseResultInline]
