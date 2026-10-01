"""Local filesystem implementation of CampusCare report storage.

This module is the storage boundary: it can later be replaced by an S3-backed
implementation without changing the API routes.

Storage structure:

storage/
└── reports/
    └── <reporter_name>/
        └── <date>/
            └── <time>_<report_id>/
                ├── <report_id>.json
                ├── <report_id>.<extension>
                └── notification.txt
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_ROOT = PROJECT_ROOT / "storage" / "reports"

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

_ID_LOCK = threading.Lock()


def _report_number(report_id: str) -> int | None:
    """Extract the numeric part from a report ID such as CC-001."""
    match = re.fullmatch(r"CC-(\d+)", report_id)
    return int(match.group(1)) if match else None


def generate_report_id() -> str:
    """Return the next report ID based on existing JSON files.

    Call this while holding _ID_LOCK when creating a report.
    """
    highest = 0

    if REPORTS_ROOT.exists():
        for json_file in REPORTS_ROOT.rglob("CC-*.json"):
            number = _report_number(json_file.stem)

            if number is not None:
                highest = max(highest, number)

    return f"CC-{highest + 1:03d}"


def _safe_user_folder(reporter_name: str) -> str:
    """Convert reporter name into a safe folder name.

    Examples:
        Piyush Chavda -> Piyush_Chavda
        John Smith -> John_Smith
        Piyush@Chavda -> PiyushChavda
    """

    # Remove unsafe characters while keeping spaces temporarily.
    safe_name = secure_filename(reporter_name)

    # Replace remaining hyphens caused by spaces with underscores.
    safe_name = safe_name.replace("-", "_")

    # Prevent multiple underscores.
    safe_name = re.sub(r"_+", "_", safe_name)

    # Remove leading/trailing underscores.
    safe_name = safe_name.strip("_")

    # Fallback if the name somehow becomes empty.
    if not safe_name:
        safe_name = "Unknown_User"

    return safe_name


def validate_image(image: FileStorage | None) -> str | None:
    """Return a safe extension, or raise ValueError for an invalid upload."""

    if image is None or not image.filename:
        return None

    filename = secure_filename(image.filename)

    extension = (
        filename.rsplit(".", 1)[-1].lower()
        if "." in filename
        else ""
    )

    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            "Image must be a JPG, JPEG, PNG, or WEBP file."
        )

    return extension


def save_image(
    image: FileStorage,
    report_folder: Path,
    report_id: str,
    extension: str,
) -> str:
    """Save one optional uploaded image and return its stored filename."""

    image_name = f"{report_id}.{extension}"

    image.save(report_folder / image_name)

    return image_name


def save_report(
    report: dict[str, Any],
    image: FileStorage | None = None,
) -> tuple[dict[str, Any], Path]:
    """Atomically allocate an ID and save the report JSON and optional image.

    Storage structure:

    reports/
        <reporterName>/
            <YYYY-MM-DD>/
                <HH-MM-SS>_<REPORT_ID>/
                    <REPORT_ID>.json
                    <REPORT_ID>.<extension>
    """

    image_extension = validate_image(image)

    timestamp = report["timestamp"]

    # Example timestamp:
    # 2026-09-22T08:30:15
    date_part, time_part = timestamp.split("T", 1)

    # Convert:
    # 08:30:15 -> 08-30-15
    time_part = time_part.split(".", 1)[0]
    time_folder = time_part.replace(":", "-")

    # Get reporter name from the submitted report.
    reporter_name = report.get("reporterName", "Unknown User")

    # Convert reporter name to a safe folder name.
    user_folder = _safe_user_folder(reporter_name)

    with _ID_LOCK:
        # Generate the next report ID.
        report_id = generate_report_id()

        # Create:
        # reports/<user>/<date>/<time>_<report_id>
        report_folder = (
            REPORTS_ROOT
            / user_folder
            / date_part
            / f"{time_folder}_{report_id}"
        )

        report_folder.mkdir(parents=True, exist_ok=False)

        try:
            # Add generated report ID and default image value.
            report = {
                **report,
                "reportId": report_id,
                "image": None,
            }

            # Save image if one was uploaded.
            if image_extension and image:
                report["image"] = save_image(
                    image,
                    report_folder,
                    report_id,
                    image_extension,
                )

            # Save report JSON.
            json_path = report_folder / f"{report_id}.json"

            json_path.write_text(
                json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        except Exception:
            # If anything fails, remove the incomplete report folder.
            for child in report_folder.iterdir():
                if child.is_file():
                    child.unlink()

            report_folder.rmdir()

            raise

    return report, report_folder


def get_all_reports() -> list[dict[str, Any]]:
    """Read every stored report, ordered newest first."""

    reports: list[dict[str, Any]] = []

    if not REPORTS_ROOT.exists():
        return reports

    # rglob continues to work with the new nested structure:
    #
    # reports/
    #   user/
    #       date/
    #           time_reportid/
    #               reportid.json
    #
    for json_file in REPORTS_ROOT.rglob("CC-*.json"):
        try:
            report = json.loads(
                json_file.read_text(encoding="utf-8")
            )

            reports.append(report)

        except (OSError, json.JSONDecodeError):
            continue

    return sorted(
        reports,
        key=lambda report: report.get("timestamp", ""),
        reverse=True,
    )


def get_report(report_id: str) -> dict[str, Any] | None:
    """Find one report by report ID."""

    for report in get_all_reports():
        if report.get("reportId") == report_id:
            return report

    return None


def get_image_path(report_id: str) -> Path | None:
    """Find the stored image for a report."""

    report = get_report(report_id)

    if not report or not report.get("image"):
        return None

    # Search recursively because reports are now stored as:
    #
    # reports/<user>/<date>/<time>_<report_id>/<image>
    #
    candidates = list(
        REPORTS_ROOT.rglob(report["image"])
    )

    return candidates[0] if candidates else None