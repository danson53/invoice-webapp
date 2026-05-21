"""
pdf_processor.py — Invoice Data Extraction Module

This module contains the pure extraction logic from Lesson 2.2's batch processor,
refactored as a reusable library. It has no file management, no Airtable calls,
and no main() function — it's designed to be imported by the Flask web app.

Exported functions:
    read_pdf(filepath)   → raw text string (or None)
    extract_fields(text, filename) → dict with all invoice fields
"""

# ── Imports ───────────────────────────────────────────────────────────────────

import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import pdfplumber   # Opens PDFs and extracts text

# Use Flask's logger when imported as a library, not the root logger
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PDF READING
# ══════════════════════════════════════════════════════════════════════════════

def read_pdf(filepath: Path) -> Optional[str]:
    """
    Open a PDF and extract all its text as a single string.

    Returns None if the file is unreadable or contains no extractable text
    (which happens with scanned-image PDFs that haven't been OCR'd).
    """
    try:
        with pdfplumber.open(filepath) as pdf:
            # Join all pages with a newline between them
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        if not text.strip():
            logger.warning(f"No text in {filepath.name} — likely a scanned image PDF")
            return None

        # Strip any HTML tags that PDF generators sometimes embed
        text = re.sub(r'<[^>]*>', '', text)
        text = re.sub(r'[<>]', '', text)

        logger.info(f"Extracted {len(text)} characters from {filepath.name}")
        return text

    except Exception as e:
        logger.error(f"Could not open PDF {filepath.name}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# FIELD EXTRACTION
# Each function searches the raw text for one field using regex patterns.
# Multiple patterns are tried in order — most specific first, fallbacks last.
#
# Regex quick reference:
#   \s   = any whitespace      \d   = any digit (0-9)
#   \b   = word boundary       ?    = previous item is optional
#   [:#] = either : or #       (…)  = capture group (what we actually extract)
# ══════════════════════════════════════════════════════════════════════════════

def extract_invoice_number(text: str) -> Optional[str]:
    """Find the invoice number. Tries labelled patterns first, vendor prefixes second."""
    patterns = [
        # "Invoice Number: INV-2024-0342" or "Invoice #: GS-1234"
        r'Invoice\s*(?:Number|No|#|Num)?\s*[:#]?\s*([A-Z]{2,4}[-\s]?\d[\d\-]+)',
        # Known vendor-prefix formats anywhere in the text
        r'(?:^|\s)(INV[-\s]?\d[\d\-]+)',
        r'(?:^|\s)(GS[-\s]?\d[\d\-]+)',
        r'(?:^|\s)(WS[-\s]?\d[\d\-]+)',
        r'(?:^|\s)(TP[-\s]?\d[\d\-]+)',
        r'(?:^|\s)(OD[-\s]?\d[\d\-]+)',
        # Fallback: anything after a # that looks like an invoice number
        r'#\s*([A-Z]{1,4}[-\s]?\d[\d\-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = match.group(1).strip()
            logger.info(f"Invoice number: {result}")
            return result
    logger.warning("Could not find invoice number")
    return None


def extract_vendor_name(text: str) -> Optional[str]:
    """
    Find the vendor company name.

    Strategy 1: Scan the first 15 lines for a line with a company suffix (Corp, Inc, LLC...).
    Strategy 2: Fall back to the first meaningful line that isn't "INVOICE".
    """
    lines = text.split("\n")
    company_suffixes = [
        "Corp", "Corporation", "Inc", "Incorporated", "LLC", "Ltd", "Limited",
        "Company", r"Co\.", "Solutions", "Services", "Supplies", "Direct",
        "Industries", "Group", "Partners",
    ]

    for line in lines[:15]:
        line = line.strip()
        if not line or len(line) < 3 or len(line) > 80:
            continue
        for suffix in company_suffixes:
            if re.search(r"\b" + suffix + r"\b", line, re.IGNORECASE):
                if ":" not in line:
                    logger.info(f"Vendor: {line}")
                    return line

    for line in lines[:10]:
        line = line.strip()
        if line and line.upper() not in ("INVOICE", "BILL", "RECEIPT") and len(line) > 5:
            logger.info(f"Vendor (fallback): {line}")
            return line

    logger.warning("Could not find vendor name")
    return None


def normalize_date(date_str: str) -> Optional[str]:
    """Convert any common date format to YYYY-MM-DD (required by Airtable)."""
    date_str = date_str.strip()
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.warning(f"Could not parse date: {date_str}")
    return None


def extract_date(text: str, label: str) -> Optional[str]:
    """
    Find a date by looking after a known label.

    label should be "Invoice Date" or "Due Date" — we match common synonyms for each.
    """
    if "invoice date" in label.lower():
        label_pattern = r'(?:Invoice\s*Date|Date\s*of\s*Invoice|Bill\s*Date|Issued?|Date)'
    elif "due date" in label.lower():
        label_pattern = r'(?:Due\s*Date|Payment\s*Due|Pay\s*By|Due\s*By|Terms\s*Due|Net\s*Due)'
    else:
        label_pattern = re.escape(label)

    date_re = r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2})'
    pattern = rf'{label_pattern}\s*[:#]?\s*{date_re}'

    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        normalized = normalize_date(match.group(1))
        logger.info(f"{label}: {normalized}")
        return normalized

    logger.warning(f"Could not find {label}")
    return None


def extract_amount(text: str) -> Optional[float]:
    """
    Extract the total invoice amount.

    Tries specific "total" label patterns first; falls back to the largest dollar
    amount in the text (the total is almost always the biggest number on an invoice).
    """
    patterns = [
        r'(?:Grand\s*Total|Total\s*Amount\s*Due|Amount\s*Due|Balance\s*Due)\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})',
        r'(?<!\w)TOTAL\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})',
        r'(?<![Ss]ub)(?<!\w)Total\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                amount = float(match.group(1).replace(",", ""))
                logger.info(f"Amount: ${amount:.2f}")
                return amount
            except ValueError:
                continue

    all_amounts = re.findall(r'\$\s*([\d,]+\.\d{2})', text)
    if all_amounts:
        largest = max(float(a.replace(",", "")) for a in all_amounts)
        logger.warning(f"Amount (fallback — largest found): ${largest:.2f}")
        return largest

    logger.warning("Could not find total amount")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT FOR CALLERS
# ══════════════════════════════════════════════════════════════════════════════

def extract_fields(text: str, filename: str) -> Dict:
    """
    Run all five extraction functions and bundle results into a dictionary.

    Also sets:
        confidence_score — fraction of required fields found (0.0–1.0)
        needs_review     — True if any required field is missing

    This is the function Flask calls after read_pdf().
    """
    logger.info(f"Extracting fields from {filename}")

    data = {
        "invoice_number": extract_invoice_number(text),
        "vendor_name":    extract_vendor_name(text),
        "invoice_date":   extract_date(text, "Invoice Date"),
        "due_date":       extract_date(text, "Due Date"),
        "total_amount":   extract_amount(text),
        "source_file":    filename,
        "extracted_at":   datetime.now().isoformat(),
    }

    required = ["invoice_number", "vendor_name", "invoice_date", "due_date", "total_amount"]
    found = sum(1 for f in required if data[f] is not None)
    data["confidence_score"] = round(found / len(required), 2)
    data["needs_review"] = data["confidence_score"] < 1.0

    missing = [f for f in required if data[f] is None]
    if missing:
        logger.warning(f"Missing fields: {missing}")

    logger.info(f"Confidence: {data['confidence_score']:.0%} ({found}/{len(required)} fields)")
    return data
