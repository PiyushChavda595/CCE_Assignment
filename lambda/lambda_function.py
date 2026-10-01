"""AWS Lambda entry point for CampusCare backend.
Receives events from AWS Lambda Function URL.
Integrates directly with:
  - Amazon S3 (Report JSON & Photo Storage)
  - Amazon SNS (Email Notifications via CampusCareNotifications topic)

No RDS, DynamoDB, API Gateway, SQS, or ALB required.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import logging
import os
import re
import sys
from typing import Any
from urllib.parse import unquote

# Add current directory to path so relative imports work inside Lambda
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import s3_service, sns_service
from utils.report_id import is_valid_report_id


logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration from Environment Variables
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "campuscare-reports-bucket")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

ALLOWED_REPORT_TYPES = {
    "Maintenance",
    "Cleanliness",
    "Complaint",
    "Suggestion",
    "Lost & Found",
    "Other",
}
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def json_response(status_code: int, data: Any) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
    }
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(data, ensure_ascii=False),
        "isBase64Encoded": False,
    }


def redirect_response(location: str) -> dict[str, Any]:
    headers = {
        "Location": location,
    }
    return {
        "statusCode": 302,
        "headers": headers,
        "body": "",
        "isBase64Encoded": False,
    }


def parse_multipart_form(body_bytes: bytes, content_type: str) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Parse multipart/form-data body into text fields and file data without external dependencies."""
    fields: dict[str, str] = {}
    file_data: dict[str, Any] | None = None

    # Extract boundary parameter
    boundary_match = re.search(r"boundary=([^;]+)", content_type)
    if not boundary_match:
        return fields, file_data

    boundary = boundary_match.group(1).strip().strip('"').encode("utf-8")
    delimiter = b"--" + boundary
    parts = body_bytes.split(delimiter)

    for part in parts:
        if not part or part == b"--" or part == b"--\r\n":
            continue

        # Split headers from body
        if b"\r\n\r\n" in part:
            header_bytes, payload = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            header_bytes, payload = part.split(b"\n\n", 1)
        else:
            continue

        # Strip trailing CRLF from payload
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        elif payload.endswith(b"\n"):
            payload = payload[:-1]

        header_str = header_bytes.decode("utf-8", errors="replace")

        # Check Content-Disposition
        disp_match = re.search(r'Content-Disposition:\s*form-data;\s*name="([^"]+)"(?:;\s*filename="([^"]*)")?', header_str, re.IGNORECASE)
        if not disp_match:
            continue

        field_name = disp_match.group(1)
        filename = disp_match.group(2)

        if filename:
            # File upload
            ct_match = re.search(r"Content-Type:\s*([^\r\n;]+)", header_str, re.IGNORECASE)
            file_ct = ct_match.group(1).strip() if ct_match else "application/octet-stream"

            file_data = {
                "fieldName": field_name,
                "filename": filename,
                "contentType": file_ct,
                "bytes": payload,
                "size": len(payload),
            }
        else:
            # Regular text field
            fields[field_name] = payload.decode("utf-8", errors="replace").strip()

    return fields, file_data


def parse_request_data(event: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Extract form fields and optional image payload from Lambda event."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    content_type = headers.get("content-type", "")

    raw_body = event.get("body", "")
    is_base64 = event.get("isBase64Encoded", False)

    body_bytes = base64.b64decode(raw_body) if is_base64 else (raw_body.encode("utf-8") if isinstance(raw_body, str) else b"")

    if "multipart/form-data" in content_type:
        return parse_multipart_form(body_bytes, content_type)

    if "application/json" in content_type or (isinstance(raw_body, str) and raw_body.strip().startswith("{")):
        try:
            json_data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            fields = {
                "type": str(json_data.get("type", "")).strip(),
                "title": str(json_data.get("title", "")).strip(),
                "location": str(json_data.get("location", "")).strip(),
                "description": str(json_data.get("description", "")).strip(),
                "reporterName": str(json_data.get("reporterName", "")).strip(),
                "reporterEmail": str(json_data.get("reporterEmail", "")).strip(),
            }
            file_data = None
            if json_data.get("imageBase64"):
                img_bytes = base64.b64decode(json_data["imageBase64"])
                filename = json_data.get("imageFilename", "photo.jpg")
                file_data = {
                    "fieldName": "image",
                    "filename": filename,
                    "contentType": json_data.get("imageContentType", "image/jpeg"),
                    "bytes": img_bytes,
                    "size": len(img_bytes),
                }
            return fields, file_data
        except Exception as e:
            logger.warning("Failed to parse JSON body: %s", e)

    return {}, None


def validate_report_submission(fields: dict[str, str], file_data: dict[str, Any] | None) -> dict[str, str]:
    """Validate submitted fields against assignment requirements."""
    errors = {}
    required = {
        "type": "Type",
        "title": "Title",
        "location": "Location",
        "description": "Description",
        "reporterName": "Reporter Name",
        "reporterEmail": "Reporter Email",
    }

    for key, label in required.items():
        if not fields.get(key):
            errors[key] = f"{label} is required."

    if fields.get("type") and fields["type"] not in ALLOWED_REPORT_TYPES:
        errors["type"] = "Choose a valid report type."

    if fields.get("reporterEmail") and not EMAIL_REGEX.match(fields["reporterEmail"]):
        errors["reporterEmail"] = "Enter a valid email address."

    if file_data and file_data.get("bytes"):
        if file_data["size"] > MAX_IMAGE_SIZE_BYTES:
            errors["image"] = "Image must be 5 MB or smaller."

        filename = file_data.get("filename", "")
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            errors["image"] = "Image must be a JPG, JPEG, PNG, or WEBP file."

    return errors


def handle_get_request(path: str) -> dict[str, Any]:
    """Handle GET requests: list reports, retrieve single report, or view image."""
    normalized_path = "/" + path.strip("/")

    # Pattern: /api/reports/CC-XXX/image or /reports/CC-XXX/image
    image_match = re.search(r"/(?:api/)?reports/([^/]+)/image$", normalized_path)
    if image_match:
        report_id = unquote(image_match.group(1))
        if not is_valid_report_id(report_id):
            return json_response(400, {"success": False, "message": "Invalid report ID."})

        report = s3_service.get_report(S3_BUCKET_NAME, report_id)
        if not report or not report.get("image"):
            return json_response(404, {"success": False, "message": "Image not found."})

        presigned_url = s3_service.get_image_presigned_url(S3_BUCKET_NAME, report_id, report["image"])
        return redirect_response(presigned_url)

    # Pattern: /api/reports/CC-XXX or /reports/CC-XXX
    single_match = re.search(r"/(?:api/)?reports/([^/]+)$", normalized_path)
    if single_match and single_match.group(1) not in ("reports", ""):
        report_id = unquote(single_match.group(1))
        if not is_valid_report_id(report_id):
            return json_response(400, {"success": False, "message": "Invalid report ID."})

        report = s3_service.get_report(S3_BUCKET_NAME, report_id)
        if not report:
            return json_response(404, {"success": False, "message": "Report not found."})
        return json_response(200, report)

    # Pattern: / or /api/reports or /reports -> list all reports
    reports = s3_service.list_all_reports(S3_BUCKET_NAME)
    return json_response(200, reports)


def handle_post_request(event: dict[str, Any]) -> dict[str, Any]:
    """Handle POST request to create a new report."""
    fields, file_data = parse_request_data(event)
    errors = validate_report_submission(fields, file_data)
    if errors:
        return json_response(400, {
            "success": False,
            "message": "Please correct the highlighted fields.",
            "errors": errors,
        })

    # Step 1: Concurrency-safe sequential Report ID claim (CC-001, CC-002, ...)
    report_id, lock_key = s3_service.claim_next_report_id(S3_BUCKET_NAME)
    logger.info("Claimed Report ID: %s (lock: %s)", report_id, lock_key)

    try:
        # Step 2: Upload image if provided
        stored_image_filename = None
        if file_data and file_data.get("bytes"):
            filename = file_data.get("filename", "")
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
            content_type = file_data.get("contentType", "image/jpeg")

            stored_image_filename = s3_service.upload_report_image(
                bucket_name=S3_BUCKET_NAME,
                report_id=report_id,
                image_bytes=file_data["bytes"],
                extension=ext,
                content_type=content_type,
            )
            logger.info("Uploaded report image to S3: %s", stored_image_filename)

        # Step 3: Construct report JSON document matching assignment schema
        report = {
            "reportId": report_id,
            "type": fields["type"],
            "title": fields["title"],
            "location": fields["location"],
            "description": fields["description"],
            "reporterName": fields["reporterName"],
            "reporterEmail": fields["reporterEmail"],
            "image": stored_image_filename,
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

        # Step 4: Upload JSON document to S3
        s3_service.upload_report_json(S3_BUCKET_NAME, report)
        logger.info("Uploaded report JSON to S3: reports/%s.json", report_id)

        # Step 5: Dispatch SNS notification to confirmed staff email topic
        sns_result = sns_service.publish_notification(SNS_TOPIC_ARN, report)
        logger.info("Dispatched SNS notification. Result: %s", sns_result)

    finally:
        # Step 6: Always release the sequential ID reservation lock
        if lock_key:
            s3_service.release_report_id_lock(S3_BUCKET_NAME, lock_key)

    return json_response(201, {
        "success": True,
        "message": "Report submitted successfully",
        "reportId": report_id,
    })


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Main AWS Lambda entry point."""
    http_context = event.get("requestContext", {}).get("http", {})
    method = (http_context.get("method") or event.get("httpMethod") or "GET").upper()
    path = event.get("rawPath") or event.get("path") or "/"

    logger.info("CampusCare Lambda invocation: method=%s, path=%s", method, path)

    try:
        if method == "GET":
            return handle_get_request(path)
        if method == "POST":
            return handle_post_request(event)
        return json_response(405, {"success": False, "message": f"Method {method} not allowed."})
    except Exception as exc:
        logger.exception("Unexpected error handling Lambda request: %s", exc)
        return json_response(500, {
            "success": False,
            "message": "Could not process request. Please try again later.",
        })
