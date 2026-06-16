"""
reports/constants.py

Centralised constants for the Reports module.
No magic strings elsewhere — import from here.
"""

from typing import Final

# ---------------------------------------------------------------------------
# Report type identifiers
# ---------------------------------------------------------------------------

REPORT_LEAD_EXPORT: Final[str] = "lead_export"
REPORT_CONVERTED_LEADS: Final[str] = "converted_leads"
REPORT_CALL_REPORT: Final[str] = "call_report"
REPORT_CALL_SUMMARY: Final[str] = "call_summary"
REPORT_DAILY_CALL: Final[str] = "daily_call_report"
REPORT_LEAD_SOURCE: Final[str] = "lead_source_report"
REPORT_LEAD_STATUS: Final[str] = "lead_status_report"
REPORT_FOLLOWUP: Final[str] = "followup_report"
REPORT_OVERDUE_FOLLOWUPS: Final[str] = "overdue_followups"
REPORT_DM: Final[str] = "dm_report"
REPORT_STATUS_HISTORY: Final[str] = "status_history_report"
REPORT_LEAD_CREATION: Final[str] = "lead_creation_report"
REPORT_CONVERSION: Final[str] = "conversion_report"
REPORT_FUNNEL: Final[str] = "funnel_report"
REPORT_DUPLICATE_LEADS: Final[str] = "duplicate_leads"
REPORT_ARCHIVED_LEADS: Final[str] = "archived_leads"
REPORT_COURSE: Final[str] = "course_report"
REPORT_USER_ASSIGNMENT: Final[str] = "user_assignment_report"

# Whitelist — every valid report_type must appear here.
VALID_REPORT_TYPES: Final[frozenset] = frozenset(
    {
        REPORT_LEAD_EXPORT,
        REPORT_CONVERTED_LEADS,
        REPORT_CALL_REPORT,
        REPORT_CALL_SUMMARY,
        REPORT_DAILY_CALL,
        REPORT_LEAD_SOURCE,
        REPORT_LEAD_STATUS,
        REPORT_FOLLOWUP,
        REPORT_OVERDUE_FOLLOWUPS,
        REPORT_DM,
        REPORT_STATUS_HISTORY,
        REPORT_LEAD_CREATION,
        REPORT_CONVERSION,
        REPORT_FUNNEL,
        REPORT_DUPLICATE_LEADS,
        REPORT_ARCHIVED_LEADS,
        REPORT_COURSE,
        REPORT_USER_ASSIGNMENT,
    }
)

# ---------------------------------------------------------------------------
# Pagination limits
# ---------------------------------------------------------------------------

DEFAULT_PAGE_SIZE: Final[int] = 50
MAX_PAGE_SIZE: Final[int] = 5000
MIN_PAGE: Final[int] = 1

# ---------------------------------------------------------------------------
# Lead funnel stage values
# ---------------------------------------------------------------------------

FUNNEL_STAGES: Final[tuple] = (
    "new",
    "contacted",
    "interested",
    "followup",
    "converted",
    "lost",
)

# ---------------------------------------------------------------------------
# Error / success messages
# ---------------------------------------------------------------------------

MSG_INVALID_REPORT_TYPE: Final[str] = "Invalid report type."
MSG_INVALID_FILTERS: Final[str] = "Invalid filters provided."
MSG_INVALID_PAGINATION: Final[str] = "Invalid pagination parameters."
MSG_PAGE_SIZE_EXCEEDED: Final[str] = (
    f"page_size exceeds maximum allowed value of {MAX_PAGE_SIZE}."
)
MSG_INVALID_DATE_FORMAT: Final[str] = (
    "Invalid date format. Expected YYYY-MM-DD."
)
MSG_INTERNAL_ERROR: Final[str] = "An internal server error occurred."
