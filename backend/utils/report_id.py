"""Report-ID helper retained as a small utility abstraction."""
import re


def is_valid_report_id(report_id: str) -> bool:
    return bool(re.fullmatch(r"CC-\d+", report_id))
