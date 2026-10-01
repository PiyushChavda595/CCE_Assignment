"""Amazon SNS service for CampusCare AWS Lambda backend.
Publishes clean plain-text email notifications to the CampusCareNotifications SNS Topic.
"""
from __future__ import annotations

import base64
from datetime import datetime
import html
import logging
import os
from pathlib import Path
from typing import Any
import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

_sns_client = None
_cached_logo_bytes: bytes | None = None
_cached_name_bytes: bytes | None = None


def get_sns_client():
    global _sns_client
    if _sns_client is None:
        _sns_client = boto3.client("sns", region_name=AWS_REGION)
    return _sns_client


def _get_s3_client():
    """Lazily obtain S3 client via s3_service or direct boto3."""
    try:
        from services.s3_service import get_s3_client
        return get_s3_client()
    except Exception:
        return boto3.client("s3", region_name=AWS_REGION)


def _load_brand_asset_bytes() -> tuple[bytes, bytes]:
    """Load optimized actual brand assets from package directory or project directory."""
    global _cached_logo_bytes, _cached_name_bytes
    if _cached_logo_bytes is not None and _cached_name_bytes is not None:
        return _cached_logo_bytes, _cached_name_bytes

    current_dir = Path(__file__).resolve().parent
    pkg_logo = current_dir.parent / "assets" / "logo.png"
    pkg_name = current_dir.parent / "assets" / "name.png"

    logo_bytes = b""
    name_bytes = b""

    if pkg_logo.is_file():
        logo_bytes = pkg_logo.read_bytes()
    if pkg_name.is_file():
        name_bytes = pkg_name.read_bytes()

    # Fallback to frontend/assets if running in development tree and pkg files not found
    if not logo_bytes or not name_bytes:
        root_dir = current_dir.parents[1]
        fe_logo = root_dir / "frontend" / "assets" / "logo.jpg"
        fe_name = root_dir / "frontend" / "assets" / "Name.jpg"
        if not logo_bytes and fe_logo.is_file():
            logo_bytes = fe_logo.read_bytes()
        if not name_bytes and fe_name.is_file():
            name_bytes = fe_name.read_bytes()

    _cached_logo_bytes = logo_bytes
    _cached_name_bytes = name_bytes
    return logo_bytes, name_bytes


def get_brand_asset_urls(bucket_name: str | None = None) -> tuple[str, str]:
    """Resolve URLs for the actual CampusCare logo.jpg and Name.jpg assets.

    Resolution strategy:
      1. If private S3 bucket is configured and accessible, ensures the logo
         and name assets exist in the bucket under 'assets/' and generates
         secure temporary presigned URLs (valid for 7 days - maximum allowed).
         This keeps the S3 bucket 100% PRIVATE while allowing Gmail, Apple Mail,
         Outlook, and other email clients to load the actual images over HTTPS.
      2. If S3 is not available (e.g. offline, local tests, or missing credentials),
         falls back to self-contained Base64 data URIs generated from the actual
         packaged image files.
    """
    logo_bytes, name_bytes = _load_brand_asset_bytes()
    logo_b64 = base64.b64encode(logo_bytes).decode("ascii") if logo_bytes else ""
    name_b64 = base64.b64encode(name_bytes).decode("ascii") if name_bytes else ""

    fallback_logo = f"data:image/png;base64,{logo_b64}" if logo_b64 else ""
    fallback_name = f"data:image/png;base64,{name_b64}" if name_b64 else ""

    if not bucket_name:
        return fallback_logo, fallback_name

    try:
        s3 = _get_s3_client()
        logo_key = "assets/campuscare_logo.png"
        name_key = "assets/campuscare_name.png"

        # Check / upload logo into private S3 bucket
        try:
            s3.head_object(Bucket=bucket_name, Key=logo_key)
        except ClientError:
            if logo_bytes:
                s3.put_object(
                    Bucket=bucket_name,
                    Key=logo_key,
                    Body=logo_bytes,
                    ContentType="image/png",
                )

        # Check / upload name wordmark into private S3 bucket
        try:
            s3.head_object(Bucket=bucket_name, Key=name_key)
        except ClientError:
            if name_bytes:
                s3.put_object(
                    Bucket=bucket_name,
                    Key=name_key,
                    Body=name_bytes,
                    ContentType="image/png",
                )

        # Generate secure temporary presigned URLs (valid for 7 days = 604800s)
        logo_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": logo_key},
            ExpiresIn=604800,
        )
        name_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": name_key},
            ExpiresIn=604800,
        )
        return logo_url, name_url
    except Exception as e:
        logger.debug("Could not generate S3 presigned URLs for brand assets, using fallback: %s", e)
        return fallback_logo, fallback_name



CATEGORY_CONFIG: dict[str, dict[str, str]] = {
    "Maintenance": {
        "color": "#1261d6",
        "bg": "#eaf5ff",
        "border": "#b9defc",
        "icon": "&#128295;",  # 🔧
    },
    "Cleanliness": {
        "color": "#168a45",
        "bg": "#ecfdf3",
        "border": "#a6f4c5",
        "icon": "&#129529;",  # 🧹
    },
    "Complaint": {
        "color": "#ea580c",
        "bg": "#fff7ed",
        "border": "#fed7aa",
        "icon": "&#9888;&#65039;",  # ⚠️
    },
    "Suggestion": {
        "color": "#0284c7",
        "bg": "#f0f9ff",
        "border": "#bae6fd",
        "icon": "&#128161;",  # 💡
    },
    "Lost & Found": {
        "color": "#0891b2",
        "bg": "#ecfeff",
        "border": "#a5f3fc",
        "icon": "&#128269;",  # 🔍
    },
    "Other": {
        "color": "#52667a",
        "bg": "#f7fafc",
        "border": "#cbd7e6",
        "icon": "&#128203;",  # 📋
    },
}

DEFAULT_CATEGORY_STYLE = {
    "color": "#1261d6",
    "bg": "#eaf5ff",
    "border": "#b9defc",
    "icon": "&#128203;",
}


def _format_timestamp(ts_str: str) -> str:
    """Format ISO timestamp into clean human-readable date and time."""
    if not ts_str:
        return "Not specified"
    try:
        cleaned = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception:
        return ts_str


def format_plain_notification(
    report: dict[str, Any],
    image_url: str | None = None,
    report_url: str | None = None,
) -> tuple[str, str]:
    """Build standardized notification subject and plain-text body matching assignment specification."""
    report_id = str(report.get("reportId", "Unknown")).strip()
    report_type = str(report.get("type", "General")).strip()
    title = str(report.get("title", "")).strip()
    location = str(report.get("location", "")).strip()
    reporter_name = str(report.get("reporterName", "")).strip()
    reporter_email = str(report.get("reporterEmail", "")).strip()
    timestamp = str(report.get("timestamp", "")).strip()
    description = str(report.get("description", "")).strip()
    status = str(report.get("status", "NEW REPORT")).strip()
    has_image = bool(report.get("image"))
    image_filename = str(report.get("image", "")).strip() if has_image else ""

    subject = f"New CampusCare Report: {report_id} [{report_type}]"

    photo_info = f"Yes ({image_filename})" if has_image else "No"
    image_line = f"Photo Link: {image_url}\n" if image_url else ""
    report_line = f"Report Link: {report_url}\n" if report_url else ""

    body = f"""==================================================
CAMPUSCARE NOTIFICATION
==================================================

Subject: New CampusCare Report

A new campus report has been submitted.

Report ID: {report_id}
Status: {status}
Type: {report_type}
Title: {title}
Location: {location}
Reported By: {reporter_name}
Reporter Email: {reporter_email}
Timestamp: {timestamp}
Photo Attached: {photo_info}
{image_line}{report_line}
Description:
{description}

==================================================
CampusCare System Dispatch • Automated Notification
CampusCare Resolution Engine • AWS Serverless Backend
==================================================
"""
    return subject, body


def format_notification(report: dict[str, Any]) -> tuple[str, str]:
    """Backwards-compatible format_notification returning (subject, plain_text_body)."""
    return format_plain_notification(report)


def format_html_notification(
    report: dict[str, Any],
    image_url: str | None = None,
    report_url: str | None = None,
    logo_url: str | None = None,
    name_url: str | None = None,
) -> str:
    """Build professionally formatted, self-contained embedded HTML email.

    Adheres to CampusCare brand identity:
      - Actual CampusCare logo.jpg and Name.jpg assets represented in header
      - Brand navy (#102a43), primary blue (#1261d6), cyan (#14b8e8), green (#168a45)
      - Responsive 600px table layout with inline CSS for universal email client support
      - Safely escaped dynamic report data to prevent HTML injection
      - Clear alert title, status badge, structured data card, photo evidence box, and footer
    """
    report_id = str(report.get("reportId", "Unknown")).strip()
    report_type = str(report.get("type", "General")).strip()
    title = str(report.get("title", "")).strip()
    location = str(report.get("location", "")).strip()
    reporter_name = str(report.get("reporterName", "")).strip()
    reporter_email = str(report.get("reporterEmail", "")).strip()
    timestamp_raw = str(report.get("timestamp", "")).strip()
    description = str(report.get("description", "")).strip()
    status = str(report.get("status", "NEW REPORT")).strip()
    has_image = bool(report.get("image"))
    image_filename = str(report.get("image", "")).strip() if has_image else ""

    # Resolve actual brand asset URLs if not passed explicitly
    if not logo_url or not name_url:
        s3_bucket = os.environ.get("S3_BUCKET_NAME", "campuscare-reports-bucket")
        auto_logo, auto_name = get_brand_asset_urls(s3_bucket)
        if not logo_url:
            logo_url = auto_logo
        if not name_url:
            name_url = auto_name

    # HTML escape all dynamic content
    esc_report_id = html.escape(report_id, quote=True)
    esc_type = html.escape(report_type, quote=True)
    esc_title = html.escape(title, quote=True)
    esc_location = html.escape(location, quote=True)
    esc_reporter_name = html.escape(reporter_name, quote=True)
    esc_reporter_email = html.escape(reporter_email, quote=True)
    esc_status = html.escape(status, quote=True)
    esc_timestamp = html.escape(_format_timestamp(timestamp_raw), quote=True)
    esc_description = html.escape(description, quote=True).replace("\r\n", "<br/>").replace("\n", "<br/>")
    esc_image_filename = html.escape(image_filename, quote=True)
    esc_logo_url = html.escape(logo_url, quote=True) if logo_url else ""
    esc_name_url = html.escape(name_url, quote=True) if name_url else ""

    # Category styling
    cat_style = CATEGORY_CONFIG.get(report_type, DEFAULT_CATEGORY_STYLE)
    cat_color = cat_style["color"]
    cat_bg = cat_style["bg"]
    cat_border = cat_style["border"]
    cat_icon = cat_style["icon"]

    # Photo evidence section
    if has_image:
        if image_url:
            esc_image_url = html.escape(image_url, quote=True)
            image_action_html = f"""<div style="margin-top: 10px;">
              <a href="{esc_image_url}" target="_blank" rel="noopener noreferrer" style="background-color: #1261d6; color: #ffffff; padding: 9px 18px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600; display: inline-block;">View Report Image &rarr;</a>
              <div style="margin-top: 6px; color: #687f96; font-size: 11px;">Secure temporary link to photo evidence in Amazon S3.</div>
            </div>"""
        else:
            image_action_html = f"""<div style="margin-top: 6px; color: #52667a; font-size: 12px;">
              Stored securely in private S3 bucket (<code>reports/{esc_image_filename}</code>).
            </div>"""

        photo_evidence_html = f"""<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #eaf5ff; border: 1px solid #b9defc; border-radius: 10px; margin-bottom: 24px;">
          <tr>
            <td style="padding: 16px 20px;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td style="vertical-align: top; width: 36px; font-size: 24px; line-height: 1;">
                    &#128247;
                  </td>
                  <td style="vertical-align: top; padding-left: 12px;">
                    <strong style="color: #102a43; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: block;">Photo Evidence Attached</strong>
                    <span style="color: #52667a; font-size: 13px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: block; margin: 3px 0 4px 0;">Filename: <code style="background-color: #ffffff; border: 1px solid #b9defc; padding: 2px 6px; border-radius: 4px; font-family: monospace; color: #1261d6; font-size: 12px;">{esc_image_filename}</code></span>
                    {image_action_html}
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>"""
    else:
        photo_evidence_html = """<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f8fafc; border: 1px dashed #cbd7e6; border-radius: 8px; margin-bottom: 24px;">
          <tr>
            <td style="padding: 12px 18px; color: #687f96; font-size: 13px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
              &#128206; No photo evidence was attached to this report.
            </td>
          </tr>
        </table>"""

    # Call-to-action button if report_url is available
    if report_url:
        esc_report_url = html.escape(report_url, quote=True)
        cta_button_html = f"""<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 8px 0 16px 0;">
          <tr>
            <td align="center">
              <a href="{esc_report_url}" target="_blank" rel="noopener noreferrer" style="background-color: #1261d6; color: #ffffff; padding: 13px 28px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 700; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: inline-block; box-shadow: 0 2px 6px rgba(18, 97, 214, 0.25);">View Report in Portal &rarr;</a>
            </td>
          </tr>
        </table>"""
    else:
        cta_button_html = ""

    html_email = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>New CampusCare Report: {esc_report_id}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f0f4f8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; color: #102a43;">
  <!-- Outer Wrapper Table -->
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f0f4f8; padding: 24px 12px;">
    <tr>
      <td align="center">
        <!-- Main Container Table (Max 600px) -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 14px rgba(16, 42, 67, 0.08); border: 1px solid #e2eaf2;">

          <!-- Top Multi-Color Brand Stripe -->
          <tr>
            <td style="height: 4px; font-size: 0; line-height: 0;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="height: 4px;">
                <tr>
                  <td width="40%" style="background-color: #1261d6; height: 4px; font-size: 0; line-height: 0;">&nbsp;</td>
                  <td width="35%" style="background-color: #14b8e8; height: 4px; font-size: 0; line-height: 0;">&nbsp;</td>
                  <td width="25%" style="background-color: #39d353; height: 4px; font-size: 0; line-height: 0;">&nbsp;</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Header Section -->
          <tr>
            <td style="background-color: #102a43; padding: 18px 26px; border-bottom: 1px solid #1a3854;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td style="vertical-align: middle;">
                    <!-- CampusCare Official Brand Block (Navbar-aligned with actual logo and name assets) -->
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; padding: 6px 14px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);">
                      <tr>
                        <!-- Actual CampusCare Logo -->
                        <td style="vertical-align: middle; padding-right: 10px;">
                          <img src="{esc_logo_url}" alt="CampusCare Logo" width="46" height="32" style="display: block; height: 32px; width: auto; max-width: 50px; border: 0; outline: none; text-decoration: none;" />
                        </td>
                        <!-- Actual CampusCare Name / Wordmark -->
                        <td style="vertical-align: middle; border-left: 1px solid #e2eaf2; padding-left: 10px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; font-weight: 800; color: #102a43;">
                          <img src="{esc_name_url}" alt="CampusCare" width="118" height="24" style="display: block; height: 24px; width: auto; max-width: 130px; border: 0; outline: none; text-decoration: none;" />
                        </td>
                      </tr>
                    </table>
                  </td>
                  <td align="right" style="vertical-align: middle;">
                    <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: inline-block; background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.16); color: #cbd7e6; padding: 6px 12px; border-radius: 20px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Campus Dispatch</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Content Body -->
          <tr>
            <td style="padding: 28px 28px 24px 28px;">

              <!-- Status Badge -->
              <div style="margin-bottom: 12px;">
                <span style="display: inline-block; background-color: #ecfdf3; color: #168a45; border: 1px solid #a6f4c5; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
                  &#9679; {esc_status}
                </span>
              </div>

              <!-- Main Title -->
              <h1 style="margin: 0 0 8px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 22px; font-weight: 800; color: #102a43; line-height: 1.3;">
                New CampusCare Report Submitted
              </h1>

              <!-- Short Message -->
              <p style="margin: 0 0 24px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.5; color: #52667a;">
                A new issue has been reported and requires attention from campus administration and facility staff.
              </p>

              <!-- Report Information Card -->
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f8fafc; border: 1px solid #e2eaf2; border-radius: 10px; margin-bottom: 24px; overflow: hidden;">
                <tr>
                  <td style="padding: 16px 20px 8px 20px;">
                    <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11px; font-weight: 700; text-transform: uppercase; color: #687f96; letter-spacing: 0.6px; display: block;">Report Overview</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding: 0 20px 16px 20px;">
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                      <!-- Row: Report ID -->
                      <tr>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; width: 38%; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Report ID</td>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; width: 62%; font-size: 13px; color: #102a43;">
                          <strong style="background-color: #eaf5ff; color: #1261d6; border: 1px solid #b9defc; padding: 2px 8px; border-radius: 4px; font-family: monospace, Courier, sans-serif; font-size: 13px;">{esc_report_id}</strong>
                        </td>
                      </tr>
                      <!-- Row: Category -->
                      <tr>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Category</td>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #102a43;">
                          <span style="background-color: {cat_bg}; color: {cat_color}; border: 1px solid {cat_border}; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 700; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">{cat_icon} {esc_type}</span>
                        </td>
                      </tr>
                      <!-- Row: Title -->
                      <tr>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Title</td>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 14px; color: #102a43; font-weight: 700; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                          {esc_title}
                        </td>
                      </tr>
                      <!-- Row: Location -->
                      <tr>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Location</td>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #102a43; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                          &#128205; {esc_location}
                        </td>
                      </tr>
                      <!-- Row: Reported By -->
                      <tr>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Submitted By</td>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #102a43; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                          {esc_reporter_name}
                        </td>
                      </tr>
                      <!-- Row: Reporter Email -->
                      <tr>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Reporter Email</td>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #102a43; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                          <a href="mailto:{esc_reporter_email}" style="color: #1261d6; text-decoration: none; font-weight: 500;">{esc_reporter_email}</a>
                        </td>
                      </tr>
                      <!-- Row: Date & Time -->
                      <tr>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Date &amp; Time</td>
                        <td style="padding: 9px 0; border-bottom: 1px solid #e2eaf2; font-size: 13px; color: #52667a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                          {esc_timestamp}
                        </td>
                      </tr>
                      <!-- Row: Status -->
                      <tr>
                        <td style="padding: 9px 0; font-size: 13px; color: #687f96; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Status</td>
                        <td style="padding: 9px 0; font-size: 13px; color: #102a43;">
                          <span style="background-color: #ecfdf3; color: #168a45; border: 1px solid #a6f4c5; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">{esc_status}</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Description Section -->
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 24px; border-collapse: separate;">
                <tr>
                  <td style="border-left: 4px solid #1261d6; background-color: #f7fafc; padding: 16px 20px; border-radius: 0 8px 8px 0; border-top: 1px solid #e2eaf2; border-right: 1px solid #e2eaf2; border-bottom: 1px solid #e2eaf2;">
                    <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11px; font-weight: 700; text-transform: uppercase; color: #687f96; letter-spacing: 0.6px; display: block; margin-bottom: 8px;">Description</span>
                    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.6; color: #102a43; word-break: break-word;">
                      {esc_description}
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Photo Evidence Section -->
              {photo_evidence_html}

              <!-- Call-to-Action (if URL available) -->
              {cta_button_html}

            </td>
          </tr>

          <!-- Footer Section -->
          <tr>
            <td style="background-color: #081524; color: #93a7be; padding: 24px 28px; text-align: center; border-top: 1px solid #1a3854;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center">
                    <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; font-weight: 700; color: #ffffff; display: block; margin-bottom: 3px;">CampusCare Resolution Engine</span>
                    <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px; color: #93a7be; display: block; margin-bottom: 14px;">A Better Campus Together &bull; Official Campus Reporting Platform</span>

                    <div style="border-top: 1px solid #1a3854; padding-top: 14px; max-width: 500px; margin: 0 auto;">
                      <p style="margin: 0 0 6px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11px; color: #687f96; line-height: 1.5;">
                        Serverless Cloud Architecture: Amazon EC2 (Nginx) &rarr; AWS Lambda Function URL &rarr; Amazon S3 + Amazon SNS
                      </p>
                      <p style="margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11px; color: #687f96; line-height: 1.5;">
                        This is an automated dispatch from CampusCare. Please do not reply directly to this email.
                      </p>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return html_email


def publish_notification(
    topic_arn: str,
    report: dict[str, Any],
    image_url: str | None = None,
    report_url: str | None = None,
    logo_url: str | None = None,
    name_url: str | None = None,
) -> dict[str, Any]:
    """Publish a report submission alert to the specified SNS Topic ARN as a clean plain-text email."""
    if not topic_arn:
        logger.warning("SNS_TOPIC_ARN is not configured; skipping notification dispatch.")
        return {"skipped": True, "reason": "SNS_TOPIC_ARN not set"}

    report_id = str(report.get("reportId", "Unknown")).strip()
    s3_bucket = os.environ.get("S3_BUCKET_NAME", "campuscare-reports-bucket")

    # Automatically resolve image URL if not passed explicitly
    if not image_url and report.get("image"):
        image_url = report.get("imageUrl") or report.get("image_url")
        if not image_url:
            try:
                from services import s3_service
                image_url = s3_service.get_image_presigned_url(
                    bucket_name=s3_bucket,
                    report_id=report_id,
                    image_filename=str(report.get("image")),
                )
            except Exception as e:
                logger.debug("Could not automatically generate S3 presigned image URL: %s", e)

    # Automatically resolve report URL if not passed explicitly
    if not report_url:
        report_url = report.get("reportUrl") or report.get("report_url")
        if not report_url:
            lambda_url = os.environ.get("LAMBDA_FUNCTION_URL", "").strip().rstrip("/")
            if lambda_url and report_id and report_id != "Unknown":
                report_url = f"{lambda_url}/api/reports/{report_id}"

    sns = get_sns_client()
    subject, plain_body = format_plain_notification(report, image_url=image_url, report_url=report_url)

    try:
        # Note: AWS SNS enforces maximum 100 characters for email subject lines
        safe_subject = subject[:98]
        response = sns.publish(
            TopicArn=topic_arn,
            Subject=safe_subject,
            Message=plain_body,
        )
        logger.info("Successfully published notification for %s. MessageId=%s", report_id, response.get("MessageId"))
        return response
    except ClientError as e:
        logger.error("Failed to publish SNS notification for %s: %s", report_id, e)
        # We do not fail the overall report creation if SNS delivery encounters an error,
        # but we log it and return error details.
        return {"error": str(e)}


