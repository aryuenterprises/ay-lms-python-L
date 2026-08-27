"""
Celery asynchronous tasks for Code Assessment.
Note: Celery workers delegate untrusted code execution to the isolated runner service.
"""
import logging
from celery import shared_task
from .services.execution_service import ExecutionService

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="code_assessment.evaluate_submission_task",
    max_retries=2,
    default_retry_delay=5,
)
def evaluate_submission_task(self, submission_id: int):
    """
    Asynchronous task to evaluate a student's code submission via the isolated runner.
    """
    logger.info("Starting background evaluation for Submission #%s", submission_id)
    try:
        service = ExecutionService()
        result = service.evaluate_submission(submission_id)
        if result:
            logger.info(
                "Completed background evaluation for Submission #%s with status: %s",
                submission_id, result.status
            )
        return {"submission_id": submission_id, "status": result.status if result else "not_found"}
    except Exception as exc:
        logger.error("Error evaluating submission #%s in background task: %s", submission_id, exc)
        try:
            self.retry(exc=exc)
        except Exception:
            logger.error("Max retries reached for submission #%s", submission_id)
            from .models import CodeSubmission
            from .constants import STATUS_SYSTEM_ERROR
            CodeSubmission.objects.filter(pk=submission_id).update(
                status=STATUS_SYSTEM_ERROR,
                error_message="System execution failed. Please re-submit.",
            )
        raise exc
