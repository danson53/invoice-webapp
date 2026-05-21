#!/usr/bin/env python3
"""
Invoice Upload Web App — Flask Backend
=======================================
This server does two things:
  1. Serves the frontend HTML/CSS/JS at http://localhost:5000
  2. Provides two JSON API endpoints:
       POST /api/process  — accepts a PDF upload, returns extracted invoice data
       POST /api/save     — accepts invoice data JSON, creates an Airtable record

HOW TO RUN:
    cd invoice-upload-webapp
    python app.py
    Then open http://localhost:5000 in your browser.

ARCHITECTURE NOTE:
    Flask serves both the frontend (templates/index.html) and the backend API.
    Having everything on the same origin (http://localhost:5000) means there are
    no CORS issues to deal with during development — or in production.
"""

# ── Imports ───────────────────────────────────────────────────────────────────

import os
import tempfile
import logging
from pathlib import Path

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS          # Allows requests from other origins (e.g. Vercel)
from dotenv import load_dotenv       # Reads variables from the .env file
import requests as http_requests     # Makes HTTP calls to the Airtable API
from urllib.parse import quote       # URL-encodes the table name (spaces → %20)

from pdf_processor import read_pdf, extract_fields   # Our extraction module


# ── Configuration ─────────────────────────────────────────────────────────────

# Load AIRTABLE_TOKEN etc. from the .env file in this same folder
load_dotenv()

AIRTABLE_TOKEN      = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID    = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "InvoiceTesting")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Flask looks for HTML files in ./templates/ and static files in ./static/
app = Flask(__name__)
CORS(app)   # Adds Access-Control-Allow-Origin headers for cross-origin requests

# Reject uploads larger than 10 MB before they hit our processing code.
# Flask raises a 413 error automatically if this is exceeded.
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the frontend upload page."""
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health():
    """Quick health check — useful for deployment monitoring."""
    return jsonify({
        "status": "ok",
        "airtable_configured": bool(AIRTABLE_TOKEN and AIRTABLE_BASE_ID),
    })


@app.route("/api/process", methods=["POST"])
def process_invoice():
    """
    Accept a PDF file upload and return extracted invoice data as JSON.

    Expects: multipart/form-data with a 'file' field containing a PDF
    Returns: { "success": true, "data": { invoice_number, vendor_name, ... } }
             or { "error": "..." } with an appropriate HTTP status code
    """
    # ── Step 1: Validate the incoming file ────────────────────────────────────
    # request.files is a dict of uploaded files keyed by the HTML field name
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Send a PDF in a 'file' field."}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": f"Only PDF files are accepted. Got: {file.filename}"}), 400

    # ── Step 2: Save to a temporary file ──────────────────────────────────────
    # We can't process an in-memory stream with pdfplumber — it needs a real file path.
    # tempfile.NamedTemporaryFile creates a file in the OS temp directory.
    # delete=False so we can read it after the 'with' block closes it.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)

        size_kb = tmp_path.stat().st_size // 1024
        logger.info(f"Received upload: {file.filename} ({size_kb} KB)")

        # ── Step 3: Extract text from the PDF ─────────────────────────────────
        text = read_pdf(tmp_path)
        if text is None:
            return jsonify({
                "error": (
                    "Could not extract text from this PDF. It may be a scanned image "
                    "(not text-based). Please check the file and try again."
                )
            }), 422   # 422 = Unprocessable Entity

        # ── Step 4: Run the field extraction ──────────────────────────────────
        data = extract_fields(text, file.filename)
        logger.info(f"Extraction complete — confidence: {data.get('confidence_score', 0):.0%}")

        # ── Step 5: Return the results ─────────────────────────────────────────
        # We only return the fields the frontend cares about (not internal metadata).
        return jsonify({
            "success": True,
            "data": {
                "invoice_number":   data.get("invoice_number"),
                "vendor_name":      data.get("vendor_name"),
                "invoice_date":     data.get("invoice_date"),
                "due_date":         data.get("due_date"),
                "total_amount":     data.get("total_amount"),
                "confidence_score": data.get("confidence_score", 0),
                "needs_review":     data.get("needs_review", False),
                "source_file":      file.filename,
            },
        })

    except Exception as e:
        logger.exception(f"Unexpected error processing {file.filename}")
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

    finally:
        # Always clean up the temp file — even if an exception occurred above
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


@app.route("/api/save", methods=["POST"])
def save_to_airtable():
    """
    Save confirmed invoice data to Airtable.

    The user has already reviewed and edited the extracted data in the frontend.
    This endpoint just takes their final values and writes them to Airtable.

    Expects: JSON body with invoice_number, vendor_name, invoice_date, due_date, total_amount
    Returns: { "success": true, "record_id": "recXXXXXX" }
             or { "error": "..." }
    """
    # ── Validate that credentials are configured ───────────────────────────────
    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
        logger.error("Airtable credentials not set — check .env file")
        return jsonify({"error": "Airtable credentials not configured. Check your .env file."}), 500

    # ── Parse the JSON body ────────────────────────────────────────────────────
    # request.get_json() returns None if the Content-Type isn't application/json
    body = request.get_json()
    if not body:
        return jsonify({"error": "Request body must be JSON with Content-Type: application/json"}), 400

    # ── Validate that all required fields are present ─────────────────────────
    required = ["invoice_number", "vendor_name", "invoice_date", "due_date", "total_amount"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # ── Build the Airtable API request ────────────────────────────────────────
    # Airtable REST API: POST to /v0/{base_id}/{table_name} creates a new record
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{quote(AIRTABLE_TABLE_NAME)}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json",
    }

    # The user has reviewed the data in the UI, so default to "Received" status.
    # Keep "Needs Review" only if they submitted with the flag still set.
    needs_review = body.get("needs_review", False)

    fields = {
        "Invoice Number": body["invoice_number"],
        "Vendor":         body["vendor_name"],
        "Invoice Date":   body["invoice_date"],
        "Due Date":       body["due_date"],
        "Amount":         float(body["total_amount"]),
        "Status":         "Needs Review" if needs_review else "Received",
        "Notes":          f"Submitted via Invoice Upload Web App. Source: {body.get('source_file', 'web upload')}",
    }

    # ── POST to Airtable ───────────────────────────────────────────────────────
    try:
        response = http_requests.post(url, headers=headers, json={"fields": fields})

        if response.status_code in (200, 201):
            record_id = response.json().get("id")
            logger.info(f"Airtable record created: {record_id} (invoice: {body['invoice_number']})")
            return jsonify({"success": True, "record_id": record_id})
        else:
            # Log and return the error message from Airtable
            err_msg = response.json().get("error", {}).get("message", response.text)
            logger.error(f"Airtable API error {response.status_code}: {err_msg}")
            return jsonify({"error": f"Airtable error: {err_msg}"}), 502   # 502 = Bad Gateway

    except Exception as e:
        logger.exception("Failed to save record to Airtable")
        return jsonify({"error": f"Save failed: {str(e)}"}), 500


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(413)
def file_too_large(e):
    """Flask raises 413 automatically when a file exceeds MAX_CONTENT_LENGTH."""
    return jsonify({"error": "File too large. Maximum size is 10 MB."}), 413


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # debug=True: Flask reloads automatically when you save changes — great for development.
    # Turn this OFF before deploying to production.
    logger.info("Starting Invoice Upload Web App on http://localhost:5000")
    app.run(debug=True, port=5000)
