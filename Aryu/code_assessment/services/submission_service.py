"""
Submission lifecycle and management service.
Directly associates submissions with the existing aryuapp.Student model.
"""
import logging
from django.db import transaction
from django.core.exceptions import ValidationError
from aryuapp.models import Student
from ..constants import (
    STATUS_QUEUED,
    MAX_SOURCE_CODE_BYTES,
    SUPPORTED_LANGUAGES,
)
from ..exceptions import (
    InvalidLanguageException,
    PayloadSizeLimitExceededException,
)
from ..models import (
    CodingProblem,
    CodingAssessment,
    CodeSubmission,
)

logger = logging.getLogger(__name__)


class SubmissionService:
    """
    Handles submission creation, validation, and execution queuing.
    """

    @staticmethod
    def create_submission(
        student: Student,
        problem: CodingProblem,
        language: str,
        source_code: str,
        assessment: CodingAssessment = None,
    ) -> CodeSubmission:
        """
        Validates payload and creates a new queued submission linked to the existing Student record.
        """
        if not student:
            raise ValidationError("A valid Student record is required to create a submission.")

        if not problem.is_active:
            raise ValidationError("This coding problem is currently inactive.")

        if language not in SUPPORTED_LANGUAGES:
            raise InvalidLanguageException(
                f"Language '{language}' is not supported. Supported languages: {', '.join(SUPPORTED_LANGUAGES)}"
            )

        if problem.supported_languages and language not in problem.supported_languages:
            raise InvalidLanguageException(
                f"Language '{language}' is not allowed for this problem. Allowed: {', '.join(problem.supported_languages)}"
            )

        encoded_code = source_code.encode("utf-8")
        if len(encoded_code) > MAX_SOURCE_CODE_BYTES:
            raise PayloadSizeLimitExceededException(
                f"Source code size ({len(encoded_code)} bytes) exceeds the limit of {MAX_SOURCE_CODE_BYTES} bytes."
            )

        with transaction.atomic():
            submission = CodeSubmission.objects.create(
                student=student,
                problem=problem,
                assessment=assessment,
                language=language,
                source_code=source_code,
                status=STATUS_QUEUED,
            )

        # Trigger async evaluation task
        try:
            from ..tasks import evaluate_submission_task
            evaluate_submission_task.delay(submission.id)
        except Exception as e:
            logger.warning("Could not dispatch async task, falling back to direct evaluation: %s", e)
            from .execution_service import ExecutionService
            ExecutionService().evaluate_submission(submission.id)

        return submission
