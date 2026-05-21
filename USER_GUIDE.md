# Invoice Upload Tool — User Guide

**For:** Finance Team, Accounts Payable
**Built by:** Precision Manufacturing AI Operations

---

## What This Does

Upload an invoice PDF and the tool automatically extracts the key data
(invoice number, vendor, dates, amount) and saves it to Airtable.
No more manual data entry.

---

## How to Use

1. Open the tool: **https://invoice-webapp-self.vercel.app**
2. Drag your invoice PDF onto the upload area, or click to browse
3. Click **Process Invoice**
4. Review the extracted data — edit any field if needed
5. Click **Save to Airtable**
6. Done. The invoice appears in Airtable immediately.

---

## What the Confidence Score Means

| Badge colour | Meaning |
|---|---|
| Green — 100% | All fields extracted automatically. Quick review and save. |
| Yellow — 60–99% | Some fields extracted. Check the highlighted ones before saving. |
| Red — below 60% | Most fields missing. Fill them in manually from the PDF. |

Missing fields are highlighted in yellow. Fill them in before saving.

---

## Troubleshooting

**"Only PDF files are accepted"**
The tool only processes PDF invoices. If your invoice is a Word doc or image,
export it to PDF first.

**Fields are missing or wrong**
The tool reads text from the PDF. If the PDF is a scanned image (a photo of
a paper invoice) rather than a digital document, text extraction won't work.
In that case, fill in the fields manually and save.

Multi-column or unusual layouts (like Tech Parts Inc.) sometimes confuse the
extractor. Edit any wrong values directly in the form before saving.

**"File too large"**
Maximum file size is 10 MB. Most invoices are well under 1 MB.

**Nothing happens after clicking Process**
Check that the tool URL is still loading (the page should show a spinner).
If it times out, contact the administrator.

---

## Supported Invoice Formats

Works automatically with:
- Standard digital invoices with clear invoice numbers and dates
- Dollar amounts with $ symbol and decimal places
- Dates in MM/DD/YYYY or YYYY-MM-DD format

Requires manual entry for:
- Scanned / photographed invoices (no embedded text)
- Unusual multi-column layouts
- Invoices in non-English languages

---

## Questions?

Contact: [your name / email]
