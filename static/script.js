/**
 * Invoice Upload Tool — Frontend Logic
 *
 * This file handles everything that happens in the browser:
 *   - File selection (drag-and-drop + click-to-browse)
 *   - Calling the Flask backend API
 *   - Showing/hiding sections based on state
 *   - Populating form fields with extracted data
 *
 * The backend API runs at the same origin (http://localhost:5000), so we use
 * relative URLs like '/api/process' instead of 'http://localhost:5000/api/process'.
 */

// ── State ─────────────────────────────────────────────────────────────────────
// We keep a reference to the selected File object and the extracted data here.
// This is our app's "memory" between the upload step and the save step.

let selectedFile = null;       // The File object the user picked
let extractedData = null;      // The JSON response from /api/process


// ── File Selection ────────────────────────────────────────────────────────────

/**
 * Called when the user picks a file via the <input type="file"> dialog.
 * event.target.files is a FileList — we take the first item.
 */
function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) setSelectedFile(file);
}

/**
 * Drag-and-drop: called continuously while a file is held over the drop zone.
 * We prevent the browser's default behaviour (opening the file) and add a CSS class.
 */
function handleDragOver(event) {
    event.preventDefault();   // Required — without this, drop won't fire
    event.stopPropagation();
    document.getElementById('dropZone').classList.add('drag-over');
}

/**
 * Drag-and-drop: called when the dragged file leaves the drop zone.
 */
function handleDragLeave(event) {
    document.getElementById('dropZone').classList.remove('drag-over');
}

/**
 * Drag-and-drop: called when the user releases the file over the drop zone.
 * event.dataTransfer.files contains the dropped files.
 */
function handleDrop(event) {
    event.preventDefault();
    event.stopPropagation();
    document.getElementById('dropZone').classList.remove('drag-over');

    const files = event.dataTransfer.files;
    if (files.length === 0) return;

    const file = files[0];

    // Validate it's a PDF before accepting
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showError('Only PDF files are accepted. Please drop a PDF invoice.');
        return;
    }

    setSelectedFile(file);
}

/**
 * Store the selected file, show its name, and enable the Process button.
 */
function setSelectedFile(file) {
    selectedFile = file;

    // Show the filename bar and hide the drop zone instructions
    document.getElementById('selectedFile').style.display = 'flex';
    document.getElementById('fileName').textContent = file.name;

    // Enable the Process button now that we have a file
    document.getElementById('processBtn').disabled = false;

    hideError();
}

/**
 * Remove the selected file and reset the upload section to its initial state.
 */
function clearFile() {
    selectedFile = null;
    document.getElementById('selectedFile').style.display = 'none';
    document.getElementById('fileName').textContent = '';
    document.getElementById('processBtn').disabled = true;

    // Reset the hidden file input so the user can select the same file again
    const input = document.getElementById('fileInput');
    input.value = '';
}


// ── Step 1: Process Invoice ───────────────────────────────────────────────────

/**
 * Send the selected PDF to the backend's /api/process endpoint.
 * On success, populate the results form with extracted data.
 */
async function processInvoice() {
    if (!selectedFile) {
        showError('Please select a PDF file first.');
        return;
    }

    // Show the loading spinner, hide everything else
    show('loadingExtract');
    hide('uploadSection');
    hideError();

    try {
        // FormData is the browser's way of sending file uploads (multipart/form-data).
        // The key 'file' must match what Flask expects: request.files['file']
        const formData = new FormData();
        formData.append('file', selectedFile);

        // fetch() sends an HTTP request and returns a Promise.
        // We await the response (it arrives asynchronously — we don't block the browser).
        const response = await fetch('/api/process', {
            method: 'POST',
            body: formData,
            // Note: Do NOT set Content-Type manually for FormData — the browser sets it
            // automatically with the correct multipart boundary.
        });

        // response.json() parses the JSON response body
        const result = await response.json();

        if (!response.ok) {
            // HTTP error (4xx, 5xx) — the backend sent an error message
            throw new Error(result.error || `Server error: ${response.status}`);
        }

        // Store the extracted data for the save step
        extractedData = result.data;

        // Populate the form fields and show the results section
        populateFields(result.data);

    } catch (err) {
        // Network error or JSON parse error
        show('uploadSection');
        showError(err.message || 'Something went wrong. Please try again.');
    } finally {
        // Always hide the loading spinner (whether success or failure)
        hide('loadingExtract');
    }
}

/**
 * Fill the results form with the extracted invoice data.
 * Fields the AI couldn't extract will be left blank and highlighted.
 */
function populateFields(data) {
    // Populate each input field
    setValue('invoiceNumber', data.invoice_number);
    setValue('vendorName',    data.vendor_name);
    setValue('invoiceDate',   data.invoice_date);    // YYYY-MM-DD — matches <input type="date">
    setValue('dueDate',       data.due_date);
    setValue('totalAmount',   data.total_amount);

    // Highlight any fields that are missing (so the user knows to fill them in)
    highlightIfMissing('invoiceNumber', data.invoice_number);
    highlightIfMissing('vendorName',    data.vendor_name);
    highlightIfMissing('invoiceDate',   data.invoice_date);
    highlightIfMissing('dueDate',       data.due_date);
    highlightIfMissing('totalAmount',   data.total_amount);

    // Update the confidence badge
    const badge = document.getElementById('confidenceBadge');
    const score = Math.round((data.confidence_score || 0) * 100);
    badge.textContent = `${score}% confident`;
    badge.className = 'confidence-badge ' + (score === 100 ? 'high' : score >= 60 ? 'medium' : 'low');

    // Show the warning notice if any fields are missing
    const reviewNotice = document.getElementById('reviewNotice');
    reviewNotice.style.display = data.needs_review ? 'block' : 'none';

    show('resultsSection');
}

/**
 * Set an input field's value, defaulting to '' if the value is null/undefined.
 */
function setValue(fieldId, value) {
    document.getElementById(fieldId).value = (value !== null && value !== undefined) ? value : '';
}

/**
 * Add a yellow highlight to a field if it has no value.
 */
function highlightIfMissing(fieldId, value) {
    const input = document.getElementById(fieldId);
    if (!value) {
        input.classList.add('missing');
    } else {
        input.classList.remove('missing');
    }
}


// ── Step 2: Save to Airtable ──────────────────────────────────────────────────

/**
 * Collect the (possibly edited) form values and POST them to /api/save.
 * The user may have corrected extraction errors, so we read from the form,
 * not from the original extractedData object.
 */
async function saveToAirtable() {
    // Read the current values from the form fields
    const invoice_number = document.getElementById('invoiceNumber').value.trim();
    const vendor_name    = document.getElementById('vendorName').value.trim();
    const invoice_date   = document.getElementById('invoiceDate').value;
    const due_date       = document.getElementById('dueDate').value;
    const total_amount   = document.getElementById('totalAmount').value;

    // Client-side validation before hitting the API
    if (!invoice_number || !vendor_name || !invoice_date || !due_date || !total_amount) {
        showError('Please fill in all fields before saving.');
        return;
    }

    if (parseFloat(total_amount) <= 0) {
        showError('Total amount must be greater than zero.');
        return;
    }

    // Show loading, hide results
    show('loadingSave');
    hide('resultsSection');
    hideError();

    try {
        // POST the invoice data as JSON
        const response = await fetch('/api/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',  // Required for request.get_json() in Flask
            },
            body: JSON.stringify({
                invoice_number,
                vendor_name,
                invoice_date,
                due_date,
                total_amount: parseFloat(total_amount),
                needs_review: extractedData?.needs_review || false,
                source_file:  extractedData?.source_file || selectedFile?.name || 'web upload',
            }),
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || `Save failed: ${response.status}`);
        }

        // Show the success screen
        document.getElementById('successMessage').textContent =
            `Invoice ${invoice_number} saved successfully. Airtable record: ${result.record_id}`;
        show('successSection');

    } catch (err) {
        show('resultsSection');
        showError(err.message || 'Failed to save to Airtable. Please try again.');
    } finally {
        hide('loadingSave');
    }
}


// ── Reset ─────────────────────────────────────────────────────────────────────

/**
 * Return the entire form to its initial state.
 * Called by "Start Over" and "Process Another Invoice" buttons.
 */
function resetForm() {
    // Clear state
    selectedFile   = null;
    extractedData  = null;

    // Reset file input
    document.getElementById('fileInput').value = '';
    document.getElementById('fileName').textContent = '';
    document.getElementById('selectedFile').style.display = 'none';
    document.getElementById('processBtn').disabled = true;

    // Clear all form fields
    ['invoiceNumber', 'vendorName', 'invoiceDate', 'dueDate', 'totalAmount'].forEach(id => {
        const el = document.getElementById(id);
        el.value = '';
        el.classList.remove('missing');
    });

    // Show upload section, hide everything else
    show('uploadSection');
    hide('resultsSection');
    hide('loadingExtract');
    hide('loadingSave');
    hide('successSection');
    hideError();
}


// ── Error Display ─────────────────────────────────────────────────────────────

function showError(message) {
    document.getElementById('errorMessage').textContent = message;
    document.getElementById('errorBanner').style.display = 'flex';
}

function hideError() {
    document.getElementById('errorBanner').style.display = 'none';
}


// ── Helpers ───────────────────────────────────────────────────────────────────

function show(id) { document.getElementById(id).style.display = 'block'; }
function hide(id) { document.getElementById(id).style.display = 'none'; }
