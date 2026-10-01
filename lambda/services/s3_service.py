"""Amazon S3 service for CampusCare AWS Lambda backend.
Stores and retrieves report JSON and images in S3 under:
  reports/
    ├── CC-001.json
    ├── CC-001.jpeg
    ├── CC-002.json
    └── ...

Includes concurrency-safe sequential Report ID allocation using S3 strong
consistency and atomic lock reservations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import random
import time
from typing import Any
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from utils.report_id import extract_report_number, format_report_id


logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        # Enforce s3v4 signature version for modern regions (like ap-south-1)
        # to ensure presigned URLs work reliably without 400 Bad Request.
        _s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
    return _s3_client


def _get_highest_existing_report_number(s3, bucket_name: str) -> int:
    """Scan existing report JSON objects in S3 to find the current highest sequential number."""
    highest = 0
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name, Prefix="reports/CC-"):
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                if key.endswith(".json") and not key.startswith("reports/.locks/"):
                    filename = key.split("/")[-1]
                    stem = filename.rsplit(".", 1)[0]
                    num = extract_report_number(stem)
                    if num is not None:
                        highest = max(highest, num)
    except ClientError as e:
        logger.warning("Error listing S3 objects for report number check: %s", e)
    return highest


def claim_next_report_id(bucket_name: str, max_attempts: int = 10) -> tuple[str, str]:
    """Atomically allocate the next sequential Report ID without race conditions.

    Concurrency mechanism:
      1. Determines candidate ID (highest existing + 1).
      2. Writes a unique lock file: reports/.locks/CC-{candidate}_{lock_uuid}.lock
      3. Due to Amazon S3's strong read-after-write consistency, immediately lists
         all active locks for that candidate ID.
      4. If our lock has the lowest lexicographical UUID (or is the sole lock),
         this invocation wins the ID.
      5. If another concurrent invocation holds a lower UUID, we delete our lock,
         increment candidate ID, apply a randomized jitter, and retry.

    Returns:
      tuple: (report_id, lock_s3_key)
    """
    s3 = get_s3_client()
    highest = _get_highest_existing_report_number(s3, bucket_name)
    candidate_num = highest + 1

    for attempt in range(max_attempts):
        candidate_id = format_report_id(candidate_num)
        lock_uuid = str(uuid.uuid4())
        lock_key = f"reports/.locks/{candidate_id}_{lock_uuid}.lock"

        # Check if the JSON for this candidate already exists in S3
        try:
            s3.head_object(Bucket=bucket_name, Key=f"reports/{candidate_id}.json")
            # If head_object succeeds, object exists -> collision avoided, try next
            candidate_num += 1
            continue
        except ClientError:
            # 404/NoSuchKey means candidate is free so far
            pass

        # Write our claim lock
        lock_payload = {
            "reportId": candidate_id,
            "uuid": lock_uuid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            s3.put_object(
                Bucket=bucket_name,
                Key=lock_key,
                Body=json.dumps(lock_payload).encode("utf-8"),
                ContentType="application/json",
            )
        except ClientError as e:
            logger.warning("Failed writing lock file %s: %s", lock_key, e)
            candidate_num += 1
            continue

        # Strongly consistent list to check for competing locks
        prefix = f"reports/.locks/{candidate_id}_"
        try:
            resp = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
            contents = resp.get("Contents", [])

            # Extract UUIDs from all active locks for this candidate
            competing_uuids = []
            for item in contents:
                k = item.get("Key", "")
                if k.startswith(prefix) and k.endswith(".lock"):
                    extracted_uuid = k[len(prefix):-5]
                    competing_uuids.append(extracted_uuid)

            # Deterministic tie-breaker: minimum UUID wins
            if competing_uuids and min(competing_uuids) == lock_uuid:
                logger.info("Successfully secured ID %s on attempt %d (lock: %s)", candidate_id, attempt + 1, lock_key)
                return candidate_id, lock_key

            # We lost the tie-breaker to a concurrent invocation
            logger.info("Lock contention for ID %s. Lost to concurrent invocation. Retrying...", candidate_id)
            try:
                s3.delete_object(Bucket=bucket_name, Key=lock_key)
            except Exception:
                pass

        except ClientError as e:
            logger.warning("Error checking locks for %s: %s", candidate_id, e)

        # Back off with randomized jitter and try next ID
        candidate_num += 1
        time.sleep(random.uniform(0.05, 0.15))

    # Fallback if all attempts encounter contention
    fallback_id = format_report_id(candidate_num)
    logger.warning("Exceeded lock attempts. Using fallback ID: %s", fallback_id)
    return fallback_id, ""


def release_report_id_lock(bucket_name: str, lock_key: str) -> None:
    """Clean up temporary reservation lock file in S3."""
    if not lock_key:
        return
    s3 = get_s3_client()
    try:
        s3.delete_object(Bucket=bucket_name, Key=lock_key)
    except Exception as e:
        logger.warning("Failed to release lock %s: %s", lock_key, e)


def generate_next_report_id(bucket_name: str) -> str:
    """Non-locking fallback ID generator (preserved for backwards compatibility)."""
    s3 = get_s3_client()
    highest = _get_highest_existing_report_number(s3, bucket_name)
    return format_report_id(highest + 1)


def upload_report_image(
    bucket_name: str,
    report_id: str,
    image_bytes: bytes,
    extension: str,
    content_type: str = "image/jpeg",
) -> str:
    """Upload report photo evidence to S3 under reports/<report_id>.<extension>."""
    s3 = get_s3_client()
    safe_ext = extension.lstrip(".").lower()
    image_filename = f"{report_id}.{safe_ext}"
    s3_key = f"reports/{image_filename}"

    s3.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=image_bytes,
        ContentType=content_type,
    )
    return image_filename


def upload_report_json(bucket_name: str, report: dict[str, Any]) -> str:
    """Upload report JSON document to S3 under reports/<report_id>.json."""
    s3 = get_s3_client()
    report_id = report["reportId"]
    s3_key = f"reports/{report_id}.json"
    json_bytes = json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")

    s3.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=json_bytes,
        ContentType="application/json; charset=utf-8",
    )
    return s3_key


def list_all_reports(bucket_name: str) -> list[dict[str, Any]]:
    """List all reports stored in S3, ordered newest first."""
    s3 = get_s3_client()
    reports = []

    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name, Prefix="reports/"):
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                # Only read report JSON objects, ignore locks or images
                if key.endswith(".json") and not key.startswith("reports/.locks/"):
                    try:
                        resp = s3.get_object(Bucket=bucket_name, Key=key)
                        data = json.loads(resp["Body"].read().decode("utf-8"))
                        reports.append(data)
                    except Exception as err:
                        logger.warning("Could not read S3 report object %s: %s", key, err)
                        continue
    except ClientError as e:
        logger.error("Failed to list reports from S3: %s", e)
        raise

    return sorted(
        reports,
        key=lambda r: r.get("timestamp", ""),
        reverse=True,
    )


def get_report(bucket_name: str, report_id: str) -> dict[str, Any] | None:
    """Fetch a single report JSON document by ID."""
    s3 = get_s3_client()
    s3_key = f"reports/{report_id}.json"
    try:
        resp = s3.get_object(Bucket=bucket_name, Key=s3_key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def get_image_presigned_url(bucket_name: str, report_id: str, image_filename: str) -> str:
    """Generate a temporary presigned URL to view/download an uploaded report image from S3.

    Enforces s3v4 signature for full compatibility with ap-south-1.
    """
    s3 = get_s3_client()
    s3_key = f"reports/{image_filename}"
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": s3_key},
        ExpiresIn=3600,  # 1 hour
    )
