"""Local stand-in for an Amazon SNS notification service."""
from pathlib import Path


def _notification_text(report: dict) -> str:
    return f"""==================================================
CAMPUSCARE NOTIFICATION
==================================================

Subject: New CampusCare Report

A new campus report has been submitted.

Report ID: {report['reportId']}
Type: {report['type']}
Title: {report['title']}
Location: {report['location']}
Reported By: {report['reporterName']}
Reporter Email: {report['reporterEmail']}

==================================================
"""


def send_notification(report: dict, report_folder: Path) -> None:
    """Print and persist the local equivalent of an SNS message."""
    message = _notification_text(report)
    print(message, flush=True)
    (report_folder / "notification.txt").write_text(message, encoding="utf-8")
