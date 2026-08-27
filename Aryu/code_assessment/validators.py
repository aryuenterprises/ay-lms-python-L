"""
Validation helpers for Code Assessment requests and models.
"""
from django.core.exceptions import ValidationError
from .constants import (
    MAX_SOURCE_CODE_BYTES,
    MAX_STDIN_BYTES,
    MIN_TIME_LIMIT_MS,
    MAX_TIME_LIMIT_MS,
    MIN_MEMORY_LIMIT_MB,
    MAX_MEMORY_LIMIT_MB,
    SUPPORTED_LANGUAGES,
)


def validate_source_code_size(value: str):
    """Ensure submitted source code does not exceed the allowed byte limit."""
    if value is None:
        raise ValidationError("Source code cannot be empty.")
    
    encoded_len = len(value.encode("utf-8"))
    if encoded_len == 0:
        raise ValidationError("Source code cannot be empty.")
    if encoded_len > MAX_SOURCE_CODE_BYTES:
        raise ValidationError(
            f"Source code size ({encoded_len} bytes) exceeds the maximum limit of {MAX_SOURCE_CODE_BYTES} bytes."
        )


def validate_stdin_size(value: str):
    """Ensure standard input payload does not exceed the allowed byte limit."""
    if value is not None:
        encoded_len = len(value.encode("utf-8"))
        if encoded_len > MAX_STDIN_BYTES:
            raise ValidationError(
                f"Input size ({encoded_len} bytes) exceeds the maximum limit of {MAX_STDIN_BYTES} bytes."
            )


def validate_time_limit(value: int):
    """Ensure time limit is within acceptable bounds."""
    if value < MIN_TIME_LIMIT_MS or value > MAX_TIME_LIMIT_MS:
        raise ValidationError(
            f"Time limit must be between {MIN_TIME_LIMIT_MS}ms and {MAX_TIME_LIMIT_MS}ms."
        )


def validate_memory_limit(value: int):
    """Ensure memory limit is within acceptable bounds."""
    if value < MIN_MEMORY_LIMIT_MB or value > MAX_MEMORY_LIMIT_MB:
        raise ValidationError(
            f"Memory limit must be between {MIN_MEMORY_LIMIT_MB}MB and {MAX_MEMORY_LIMIT_MB}MB."
        )


def validate_supported_language_choice(value: str):
    """Ensure the language identifier is part of the global allowlist."""
    if value not in SUPPORTED_LANGUAGES:
        raise ValidationError(
            f"Language '{value}' is not supported. Allowed languages: {', '.join(SUPPORTED_LANGUAGES)}"
        )
