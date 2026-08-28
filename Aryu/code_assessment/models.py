"""
Database models for Online Code Assessment module.
Directly integrates with the existing aryuapp.Student model as the single source of truth for students.
"""
from django.db import models
from django.utils.text import slugify
from .constants import (
    DIFFICULTY_CHOICES,
    DIFFICULTY_EASY,
    LANGUAGE_CHOICES,
    LANGUAGE_CONFIG,
    SUBMISSION_STATUS_CHOICES,
    STATUS_QUEUED,
    STATUS_ACCEPTED,
    TEST_CASE_STATUS_CHOICES,
    DEFAULT_TIME_LIMIT_MS,
    DEFAULT_MEMORY_LIMIT_MB,
    SUPPORTED_LANGUAGES,
)
from .validators import (
    validate_source_code_size,
    validate_stdin_size,
    validate_time_limit,
    validate_memory_limit,
)


class CodingProblem(models.Model):
    """
    Represents a coding problem/question for students to practice or complete in assessments.
    """
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    description = models.TextField(help_text="Problem statement in Markdown")
    difficulty = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default=DIFFICULTY_EASY,
        db_index=True,
    )
    constraints = models.TextField(blank=True, default="", help_text="Problem constraints (e.g. 1 <= N <= 10^5)")
    input_format = models.TextField(blank=True, default="", help_text="Explanation of input format")
    output_format = models.TextField(blank=True, default="", help_text="Explanation of output format")
    sample_explanation = models.TextField(blank=True, default="", help_text="Explanation of sample cases")

    time_limit_ms = models.PositiveIntegerField(
        default=DEFAULT_TIME_LIMIT_MS,
        validators=[validate_time_limit],
        help_text="Maximum CPU time allowed per test case in milliseconds",
    )
    memory_limit_mb = models.PositiveIntegerField(
        default=DEFAULT_MEMORY_LIMIT_MB,
        validators=[validate_memory_limit],
        help_text="Maximum RAM allowed per test case in megabytes",
    )

    supported_languages = models.JSONField(
        default=list,
        help_text="Allowed programming language codes, e.g. ['python', 'javascript', 'java', 'cpp']",
    )
    starter_code = models.JSONField(
        default=dict,
        blank=True,
        help_text="Starter code templates keyed by language, e.g. {'python': '...', 'java': '...'}",
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Category/topic tags, e.g. ['array', 'string', 'recursion']",
    )

    courses = models.ManyToManyField(
        "courses.Course",
        blank=True,
        related_name="coding_problems",
        help_text="Associated courses for which this problem is relevant",
    )

    is_active = models.BooleanField(default=True, db_index=True)
    total_submissions_count = models.PositiveIntegerField(default=0)
    accepted_submissions_count = models.PositiveIntegerField(default=0)

    created_by = models.CharField(max_length=100, blank=True, null=True)
    created_by_type = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "code_assessment_problem"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["difficulty", "is_active"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.difficulty.capitalize()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "problem"
            slug = base_slug
            counter = 1
            while CodingProblem.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        if not self.supported_languages:
            self.supported_languages = list(SUPPORTED_LANGUAGES)

        super().save(*args, **kwargs)

    @property
    def acceptance_rate(self) -> float:
        """Returns the percentage of accepted submissions."""
        if self.total_submissions_count == 0:
            return 0.0
        return round((self.accepted_submissions_count / self.total_submissions_count) * 100.0, 2)

    def get_starter_code_for(self, language: str) -> str:
        """Returns the starter code for a specific language."""
        if isinstance(self.starter_code, dict) and language in self.starter_code:
            return self.starter_code[language]
        if language in LANGUAGE_CONFIG:
            return LANGUAGE_CONFIG[language].get("starter_code", "")
        return ""


class CodingTestCase(models.Model):
    """
    Test case for evaluating code submissions.
    Hidden test cases are strictly guarded and NEVER exposed to students.
    """
    problem = models.ForeignKey(
        CodingProblem,
        on_delete=models.CASCADE,
        related_name="test_cases",
    )
    input_data = models.TextField(
        blank=True,
        default="",
        validators=[validate_stdin_size],
        help_text="Standard input passed to the program via stdin",
    )
    expected_output = models.TextField(
        blank=True,
        default="",
        help_text="Expected standard output produced by the program on stdout",
    )
    is_sample = models.BooleanField(
        default=False,
        db_index=True,
        help_text="If True, visible as a sample test case in problem description and test runner",
    )
    is_hidden = models.BooleanField(
        default=True,
        db_index=True,
        help_text="If True, hidden from students and used solely for submission scoring",
    )
    explanation = models.TextField(
        blank=True,
        default="",
        help_text="Optional explanation displayed for sample test cases",
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "code_assessment_testcase"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["problem", "is_sample"]),
            models.Index(fields=["problem", "is_hidden"]),
        ]

    def __str__(self):
        case_type = "Sample" if self.is_sample else "Hidden"
        return f"TestCase #{self.id} [{case_type}] for {self.problem.title}"


class CodingAssessment(models.Model):
    """
    Represents a timed or untimed coding exam / interview test consisting of multiple problems.
    """
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coding_assessments",
        help_text="Associated course for this assessment (optional)",
    )
    duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Assessment time limit in minutes (0 means untimed / practice)",
    )
    passing_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=60.00,
        help_text="Minimum score percentage required to pass",
    )
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    created_by = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "code_assessment_assessment"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["course", "is_active"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "assessment"
            slug = base_slug
            counter = 1
            while CodingAssessment.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class AssessmentProblem(models.Model):
    """
    Associates a problem with an assessment with ordering and points.
    """
    assessment = models.ForeignKey(
        CodingAssessment,
        on_delete=models.CASCADE,
        related_name="assessment_problems",
    )
    problem = models.ForeignKey(
        CodingProblem,
        on_delete=models.CASCADE,
        related_name="assessment_associations",
    )
    order = models.PositiveIntegerField(default=0)
    points = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "code_assessment_assessment_problem"
        ordering = ["order", "id"]
        unique_together = [("assessment", "problem")]

    def __str__(self):
        return f"{self.assessment.title} -> {self.problem.title} ({self.points} pts)"


class AssessmentAttempt(models.Model):
    """
    Tracks a student's attempt on a coding assessment.
    Directly references the existing Student model (aryuapp.Student).
    """
    student = models.ForeignKey(
        "aryuapp.Student",
        on_delete=models.CASCADE,
        related_name="assessment_attempts",
        help_text="Direct relationship to existing Student model in aryuapp",
    )
    assessment = models.ForeignKey(
        CodingAssessment,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    is_passed = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "code_assessment_assessment_attempt"
        ordering = ["-started_at"]
        unique_together = [("student", "assessment")]
        indexes = [
            models.Index(fields=["student", "assessment"]),
        ]

    def __str__(self):
        return f"Attempt by Student #{self.student_id} on {self.assessment.title} ({self.score}%)"


class CodeSubmission(models.Model):
    """
    Tracks a student's solution submission and its evaluation results.
    Directly references the existing Student model (aryuapp.Student).
    Redundant student info fields (name, email, phone) are strictly omitted.
    """
    student = models.ForeignKey(
        "aryuapp.Student",
        on_delete=models.CASCADE,
        related_name="code_submissions",
        help_text="Direct relationship to existing Student model in aryuapp",
    )
    problem = models.ForeignKey(
        CodingProblem,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    assessment = models.ForeignKey(
        CodingAssessment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    language = models.CharField(max_length=30, choices=LANGUAGE_CHOICES)
    source_code = models.TextField(validators=[validate_source_code_size])

    status = models.CharField(
        max_length=30,
        choices=SUBMISSION_STATUS_CHOICES,
        default=STATUS_QUEUED,
        db_index=True,
    )
    score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    total_test_cases = models.PositiveIntegerField(default=0)
    passed_test_cases = models.PositiveIntegerField(default=0)

    execution_time_ms = models.PositiveIntegerField(default=0, help_text="Peak runtime in ms")
    memory_used_kb = models.PositiveIntegerField(default=0, help_text="Peak memory in KB")

    error_message = models.TextField(blank=True, default="", help_text="Sanitized execution error summary")
    compile_output = models.TextField(blank=True, default="", help_text="Sanitized compiler diagnostic output")

    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "code_assessment_submission"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["student", "submitted_at"]),
            models.Index(fields=["problem", "status"]),
            models.Index(fields=["assessment", "student"]),
        ]

    def __str__(self):
        return f"Submission #{self.id} [{self.status}] by Student #{self.student_id} for {self.problem.title}"

    @property
    def is_accepted(self) -> bool:
        return self.status == STATUS_ACCEPTED


class SubmissionTestCaseResult(models.Model):
    """
    Stores individual test case execution outcome for a submission.
    Note: For hidden test cases, stdout/stdin are never transmitted to students.
    """
    submission = models.ForeignKey(
        CodeSubmission,
        on_delete=models.CASCADE,
        related_name="test_case_results",
    )
    test_case = models.ForeignKey(
        CodingTestCase,
        on_delete=models.CASCADE,
        related_name="submission_results",
    )
    status = models.CharField(
        max_length=30,
        choices=TEST_CASE_STATUS_CHOICES,
        default=STATUS_QUEUED,
    )
    execution_time_ms = models.PositiveIntegerField(default=0)
    memory_used_kb = models.PositiveIntegerField(default=0)
    stdout = models.TextField(blank=True, default="")
    stderr = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "code_assessment_submission_testcase_result"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["submission", "status"]),
        ]

    def __str__(self):
        return f"Result for Submission #{self.submission_id}, TestCase #{self.test_case_id}: {self.status}"
