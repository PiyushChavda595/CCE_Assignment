"""Report ID utilities for AWS Lambda environment.
Follows the format CC-001, CC-002, etc.
"""
from __future__ import annotations

import re


REPORT_ID_PATTERN = re.compile(r"^CC-(\d+)$")


def is_valid_report_id(report_id: str) -> bool:
    """Validate whether report_id matches the CC-XXX format."""
    return bool(REPORT_ID_PATTERN.fullmatch(report_id))


def extract_report_number(report_id: str) -> int | None:
    """Extract numeric suffix from CC-001 -> 1."""
    match = REPORT_ID_PATTERN.fullmatch(report_id)
    return int(match.group(1)) if match else None


def format_report_id(number: int) -> str:
    """Format integer into CC-XXX format."""
    return f"CC-{number:03d}"
