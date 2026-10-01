#!/usr/bin/env python3
"""Packaging utility for CampusCare AWS Lambda function.
Packages lambda_function.py, services/, and utils/ into a clean zip archive
ready to deploy directly to AWS Lambda via AWS Console or AWS CLI.
"""
import os
from pathlib import Path
import zipfile


def build_lambda_zip():
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[1]
    lambda_src = repo_root / "lambda"
    dist_dir = repo_root / "deployment" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / "campuscare_lambda.zip"

    print(f"Building Lambda deployment package from: {lambda_src}")
    print(f"Destination: {zip_path}")

    files_added = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(lambda_src):
            # Ignore __pycache__ and hidden files
            dirs[:] = [d for d in dirs if not d.startswith("__") and not d.startswith(".")]
            for file in files:
                if file.endswith(".pyc") or file.startswith("."):
                    continue
                full_path = Path(root) / file
                archive_name = full_path.relative_to(lambda_src)
                zipf.write(full_path, arcname=archive_name)
                print(f"  + Added: {archive_name}")
                files_added += 1

    size_kb = zip_path.stat().st_size / 1024
    print("--------------------------------------------------")
    print(f"[OK] Archive created successfully: {zip_path}")
    print(f"  Files included: {files_added}")
    print(f"  Package size: {size_kb:.1f} KB")
    print("--------------------------------------------------")
    return zip_path


if __name__ == "__main__":
    build_lambda_zip()
