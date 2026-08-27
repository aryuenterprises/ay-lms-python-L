"""
Custom exceptions for the Code Assessment application.
"""
from rest_framework.exceptions import APIException
from rest_framework import status


class CodeAssessmentException(APIException):
    """Base exception for code assessment errors."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "An error occurred during code assessment."
    default_code = "code_assessment_error"


class InvalidLanguageException(CodeAssessmentException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The specified programming language is not supported for this problem."
    default_code = "invalid_language"


class PayloadSizeLimitExceededException(CodeAssessmentException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Source code or input data exceeds the maximum allowed payload size."
    default_code = "payload_too_large"


class RunnerUnavailableException(CodeAssessmentException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The secure code execution runner service is temporarily unavailable."
    default_code = "runner_unavailable"


class ExecutionSecurityException(CodeAssessmentException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The execution was blocked by the security sandbox policy."
    default_code = "security_violation"


class SubmissionNotFoundException(CodeAssessmentException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested code submission was not found."
    default_code = "submission_not_found"


class ProblemNotFoundException(CodeAssessmentException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested coding problem was not found."
    default_code = "problem_not_found"


class AssessmentNotFoundException(CodeAssessmentException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested coding assessment was not found."
    default_code = "assessment_not_found"
