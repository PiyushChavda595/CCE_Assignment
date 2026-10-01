"""Unit tests for CampusCare AWS Lambda backend, S3 service, SNS service, and report ID utility."""
from datetime import datetime, timezone
import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add lambda directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lambda")))

# pyrefly: ignore [missing-import]
from utils.report_id import is_valid_report_id, extract_report_number, format_report_id
import services.s3_service as s3_service
import services.sns_service as sns_service
import lambda_function


class TestReportId(unittest.TestCase):
    def test_validation(self):
        self.assertTrue(is_valid_report_id("CC-001"))
        self.assertTrue(is_valid_report_id("CC-999"))
        self.assertTrue(is_valid_report_id("CC-1024"))
        self.assertFalse(is_valid_report_id("CC-ABC"))
        self.assertFalse(is_valid_report_id("001"))
        self.assertFalse(is_valid_report_id(""))

    def test_extraction(self):
        self.assertEqual(extract_report_number("CC-001"), 1)
        self.assertEqual(extract_report_number("CC-042"), 42)
        self.assertEqual(extract_report_number("CC-100"), 100)
        self.assertIsNone(extract_report_number("INVALID"))

    def test_formatting(self):
        self.assertEqual(format_report_id(1), "CC-001")
        self.assertEqual(format_report_id(15), "CC-015")
        self.assertEqual(format_report_id(100), "CC-100")


class TestS3Service(unittest.TestCase):
    @patch("services.s3_service.get_s3_client")
    def test_generate_next_report_id_empty(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        mock_s3.get_paginator.return_value = paginator

        next_id = s3_service.generate_next_report_id("test-bucket")
        self.assertEqual(next_id, "CC-001")

    @patch("services.s3_service.get_s3_client")
    def test_generate_next_report_id_existing(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "Contents": [
                {"Key": "reports/CC-001.json"},
                {"Key": "reports/CC-001.jpeg"},
                {"Key": "reports/CC-002.json"},
            ]
        }]
        mock_s3.get_paginator.return_value = paginator

        next_id = s3_service.generate_next_report_id("test-bucket")
        self.assertEqual(next_id, "CC-003")

    @patch("services.s3_service.get_s3_client")
    def test_claim_next_report_id_concurrency_safe(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        # Simulate existing reports: CC-001, CC-002
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "Contents": [
                {"Key": "reports/CC-001.json"},
                {"Key": "reports/CC-002.json"},
            ]
        }]
        mock_s3.get_paginator.return_value = paginator

        # Candidate CC-003 head_object raises 404 (does not exist yet)
        from botocore.exceptions import ClientError
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "head_object"
        )

        # In list_objects_v2, return our lock as the only lock for CC-003
        def list_side_effect(**kwargs):
            prefix = kwargs.get("Prefix", "")
            return {"Contents": [{"Key": prefix + "11111111-1111-1111-1111-111111111111.lock"}]}

        mock_s3.list_objects_v2.side_effect = list_side_effect

        with patch("uuid.uuid4", return_value="11111111-1111-1111-1111-111111111111"):
            report_id, lock_key = s3_service.claim_next_report_id("test-bucket")

        self.assertEqual(report_id, "CC-003")
        self.assertIn("reports/.locks/CC-003_", lock_key)
        mock_s3.put_object.assert_called()

    @patch("services.s3_service.get_s3_client")
    def test_release_report_id_lock(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        s3_service.release_report_id_lock("test-bucket", "reports/.locks/CC-003_123.lock")
        mock_s3.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="reports/.locks/CC-003_123.lock"
        )

    @patch("services.s3_service.get_s3_client")
    def test_upload_report_image(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        filename = s3_service.upload_report_image(
            bucket_name="test-bucket",
            report_id="CC-005",
            image_bytes=b"fake-image-bytes",
            extension="png",
            content_type="image/png",
        )
        self.assertEqual(filename, "CC-005.png")
        mock_s3.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="reports/CC-005.png",
            Body=b"fake-image-bytes",
            ContentType="image/png",
        )

    @patch("services.s3_service.get_s3_client")
    def test_upload_report_json(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        report = {
            "reportId": "CC-001",
            "type": "Maintenance",
            "title": "Projector not working",
            "location": "Lab 204",
            "description": "Projector turns on but does not display anything.",
            "reporterName": "Rahul Sharma",
            "reporterEmail": "rahul@example.com",
            "image": "CC-001.jpg",
            "timestamp": "2026-09-09T18:30:00",
        }
        key = s3_service.upload_report_json("test-bucket", report)
        self.assertEqual(key, "reports/CC-001.json")
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        self.assertEqual(call_kwargs["Bucket"], "test-bucket")
        self.assertEqual(call_kwargs["Key"], "reports/CC-001.json")
        uploaded_json = json.loads(call_kwargs["Body"].decode("utf-8"))
        self.assertEqual(uploaded_json["reportId"], "CC-001")


class TestSNSService(unittest.TestCase):
    def test_format_notification(self):
        report = {
            "reportId": "CC-001",
            "type": "Maintenance",
            "title": "Projector not working",
            "location": "Lab 204",
            "description": "Projector bulb burned out.",
            "reporterName": "Rahul Sharma",
            "reporterEmail": "rahul@example.com",
            "timestamp": "2026-09-09T18:30:00",
            "image": "CC-001.jpeg",
        }
        subject, body = sns_service.format_notification(report)
        self.assertIn("CC-001", subject)
        self.assertIn("Maintenance", subject)
        self.assertIn("Lab 204", body)
        self.assertIn("Rahul Sharma", body)
        self.assertIn("Projector bulb burned out.", body)

    @patch("services.sns_service.get_sns_client")
    def test_publish_notification_ap_south_1(self, mock_get_sns):
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns
        mock_sns.publish.return_value = {"MessageId": "msg-12345"}

        report = {
            "reportId": "CC-002",
            "type": "Cleanliness",
            "title": "Spill in hallway",
            "location": "Block C",
            "reporterName": "Priya Patel",
            "reporterEmail": "priya@example.com",
            "timestamp": "2026-09-28T12:00:00",
            "description": "Coffee spilled near room 101",
            "image": None,
        }
        res = sns_service.publish_notification("arn:aws:sns:ap-south-1:123456789012:CampusCareNotifications", report)
        self.assertEqual(res["MessageId"], "msg-12345")
        mock_sns.publish.assert_called_once()

        # Verify MessageStructure='json' and payload structure
        call_kwargs = mock_sns.publish.call_args[1]
        self.assertEqual(call_kwargs["MessageStructure"], "json")
        payload = json.loads(call_kwargs["Message"])
        self.assertIn("default", payload)
        self.assertIn("email", payload)
        self.assertIn("CC-002", payload["default"])
        self.assertIn("<!DOCTYPE html", payload["email"])
        self.assertIn("CampusCare", payload["email"])

    def test_format_html_notification(self):
        report = {
            "reportId": "CC-010",
            "type": "Maintenance",
            "title": "Broken window in Room 102",
            "location": "Academic Block A",
            "reporterName": "Ananya Roy",
            "reporterEmail": "ananya@example.com",
            "timestamp": "2026-09-29T10:15:00+00:00",
            "description": "Window latch is loose and glass is cracked.\nPlease send technician.",
            "image": "CC-010.jpg",
        }
        html_content = sns_service.format_html_notification(
            report,
            image_url="https://s3.amazonaws.com/test-bucket/reports/CC-010.jpg?sig=test",
            report_url="https://test.lambda-url.ap-south-1.on.aws/api/reports/CC-010",
        )
        self.assertIn("<!DOCTYPE html", html_content)
        self.assertIn("CampusCare", html_content)
        self.assertIn("CC-010", html_content)
        self.assertIn("Maintenance", html_content)
        self.assertIn("Academic Block A", html_content)
        self.assertIn("Ananya Roy", html_content)
        self.assertIn("ananya@example.com", html_content)
        self.assertIn("Window latch is loose and glass is cracked.<br/>Please send technician.", html_content)
        self.assertIn("View Report Image", html_content)
        self.assertIn("View Report in Portal", html_content)
        self.assertIn("NEW REPORT", html_content)
        self.assertIn("CampusCare Logo", html_content)

    def test_format_html_notification_escaping(self):
        malicious_report = {
            "reportId": "CC-999",
            "type": "Other",
            "title": "<script>alert('xss')</script>",
            "location": "Room <b>1</b> & 2",
            "reporterName": 'Jane "Danger" Doe',
            "reporterEmail": "danger@example.com",
            "timestamp": "2026-09-29T12:00:00",
            "description": '<img src=x onerror=alert(1)> & "quotes"',
            "image": None,
        }
        html_content = sns_service.format_html_notification(malicious_report)
        self.assertNotIn("<script>", html_content)
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", html_content)
        self.assertNotIn("<img src=x", html_content)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt; &amp; &quot;quotes&quot;", html_content)
        self.assertIn("Room &lt;b&gt;1&lt;/b&gt; &amp; 2", html_content)
        self.assertIn("Jane &quot;Danger&quot; Doe", html_content)


class TestLambdaHandler(unittest.TestCase):
    def test_cors_options(self):
        event = {
            "requestContext": {"http": {"method": "OPTIONS"}},
            "rawPath": "/api/reports",
        }
        res = lambda_function.lambda_handler(event, None)
        self.assertEqual(res["statusCode"], 204)
        self.assertIn("Access-Control-Allow-Origin", res["headers"])

    @patch("services.s3_service.list_all_reports")
    def test_get_reports_list(self, mock_list):
        mock_list.return_value = [
            {"reportId": "CC-002", "title": "Second"},
            {"reportId": "CC-001", "title": "First"},
        ]
        event = {
            "requestContext": {"http": {"method": "GET"}},
            "rawPath": "/api/reports",
        }
        res = lambda_function.lambda_handler(event, None)
        self.assertEqual(res["statusCode"], 200)
        body = json.loads(res["body"])
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["reportId"], "CC-002")

    @patch("services.sns_service.publish_notification")
    @patch("services.s3_service.upload_report_json")
    @patch("services.s3_service.upload_report_image")
    @patch("services.s3_service.release_report_id_lock")
    @patch("services.s3_service.claim_next_report_id")
    def test_post_report_json(self, mock_claim_id, mock_release_lock, mock_up_img, mock_up_json, mock_sns):
        mock_claim_id.return_value = ("CC-003", "reports/.locks/CC-003_test.lock")
        mock_sns.return_value = {"MessageId": "msg-1"}

        payload = {
            "type": "Maintenance",
            "title": "Air Conditioner Leaking",
            "location": "Room 305",
            "description": "Water dripping from the wall AC unit.",
            "reporterName": "Amit Verma",
            "reporterEmail": "amit@campus.edu",
        }
        event = {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/api/reports",
            "headers": {"content-type": "application/json"},
            "body": json.dumps(payload),
            "isBase64Encoded": False,
        }
        res = lambda_function.lambda_handler(event, None)
        self.assertEqual(res["statusCode"], 201)
        data = json.loads(res["body"])
        self.assertTrue(data["success"])
        self.assertEqual(data["reportId"], "CC-003")

        mock_up_json.assert_called_once()
        mock_sns.assert_called_once()
        mock_release_lock.assert_called_once()

    def test_post_validation_error(self):
        # Missing title and invalid email
        payload = {
            "type": "Maintenance",
            "title": "",
            "location": "Room 305",
            "description": "Water dripping",
            "reporterName": "Amit",
            "reporterEmail": "not-an-email",
        }
        event = {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/api/reports",
            "headers": {"content-type": "application/json"},
            "body": json.dumps(payload),
            "isBase64Encoded": False,
        }
        res = lambda_function.lambda_handler(event, None)
        self.assertEqual(res["statusCode"], 400)
        data = json.loads(res["body"])
        self.assertFalse(data["success"])
        self.assertIn("title", data["errors"])
        self.assertIn("reporterEmail", data["errors"])


if __name__ == "__main__":
    unittest.main()
