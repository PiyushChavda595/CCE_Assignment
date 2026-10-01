from datetime import datetime
from pathlib import Path
import re
import sys

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

sys.path.insert(0, str(Path(__file__).resolve().parent))
from services import notification_service, storage_service  # noqa: E402
from utils.report_id import is_valid_report_id  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB total request limit
CORS(app)

REQUIRED_FIELDS = {
    "type": "Type",
    "title": "Title",
    "location": "Location",
    "description": "Description",
    "reporterName": "Reporter Name",
    "reporterEmail": "Reporter Email",
}
REPORT_TYPES = {"Maintenance", "Cleanliness", "Complaint", "Suggestion", "Lost & Found", "Other"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_form() -> tuple[dict, dict]:
    data = {field: request.form.get(field, "").strip() for field in REQUIRED_FIELDS}
    errors = {field: f"{label} is required." for field, label in REQUIRED_FIELDS.items() if not data[field]}
    if data["type"] and data["type"] not in REPORT_TYPES:
        errors["type"] = "Choose a valid report type."
    if data["reporterEmail"] and not EMAIL_PATTERN.match(data["reporterEmail"]):
        errors["reporterEmail"] = "Enter a valid email address."
    return data, errors


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(_error):
    return jsonify(success=False, message="Image must be 5 MB or smaller."), 413


@app.post("/api/reports")
def create_report():
    data, errors = validate_form()
    if errors:
        return jsonify(success=False, message="Please correct the highlighted fields.", errors=errors), 400
    report = {**data, "timestamp": datetime.now().replace(microsecond=0).isoformat()}
    try:
        saved_report, report_folder = storage_service.save_report(report, request.files.get("image"))
        notification_service.send_notification(saved_report, report_folder)
    except ValueError as error:
        return jsonify(success=False, message=str(error)), 400
    except Exception:
        app.logger.exception("Could not save report")
        return jsonify(success=False, message="Could not save the report. Please try again."), 500
    return jsonify(success=True, message="Report submitted successfully", reportId=saved_report["reportId"]), 201


@app.get("/api/reports")
def list_reports():
    return jsonify(storage_service.get_all_reports())


@app.get("/api/reports/<report_id>")
def retrieve_report(report_id):
    if not is_valid_report_id(report_id):
        return jsonify(success=False, message="Invalid report ID."), 400
    report = storage_service.get_report(report_id)
    if not report:
        return jsonify(success=False, message="Report not found."), 404
    return jsonify(report)


@app.get("/api/reports/<report_id>/image")
def retrieve_image(report_id):
    if not is_valid_report_id(report_id):
        return jsonify(success=False, message="Invalid report ID."), 400
    image_path = storage_service.get_image_path(report_id)
    if not image_path:
        return jsonify(success=False, message="Image not found."), 404
    return send_file(image_path)


if __name__ == "__main__":
    print("CampusCare backend running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
