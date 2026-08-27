# Saksham — Tool Contract Specification

This document defines every tool available to the Saksham WorkerEngine. Each tool is described with its purpose, inputs, outputs, determinism, failure modes, and guarantees. The source code is authoritative.

---

## Tool Catalog

| # | Tool | Module | Category |
|---|------|--------|----------|
| 1 | Application Validation | `app/tools/validation.py` | DETERMINISTIC |
| 2 | File Validation | `app/tools/document_processing.py` | DETERMINISTIC |
| 3 | OCR | `app/tools/ocr.py` | DOCUMENT PROCESSING |
| 4 | PDF Processing | `app/tools/pdf_processing.py` | DOCUMENT PROCESSING |
| 5 | Structured Field Extraction | `app/tools/field_extraction.py` | DETERMINISTIC |
| 6 | Document Processing Pipeline | `app/tools/document_processing.py` | DOCUMENT PROCESSING |
| 7 | Data Comparison | `app/tools/comparison.py` | DETERMINISTIC |
| 8 | Risk Assessment | `app/tools/risk.py` | DETERMINISTIC |
| 9 | AI Recommendation | `app/tools/llm_analysis.py` | AI / PROBABILISTIC |
| 10 | Extraction Router | `app/tools/extraction.py` | DOCUMENT PROCESSING |
| 11 | Escalation | `app/tools/escalation.py` | ESCALATION |
| 12 | Workflow Memory | `app/memory/store.py` | STATE / MEMORY |
| 13 | Document Store | `app/memory/store.py` | STATE / MEMORY |
| 14 | Database | `app/memory/database.py` | STATE / MEMORY |
| 15 | Audit Logger | `app/audit/logger.py` | AUDIT / OBSERVABILITY |

---

## Tool Contracts

------------------------------------------------------------
Tool: Application Validation
------------------------------------------------------------

Purpose:
Validate that an incoming onboarding application contains all required fields with valid formats.

Module:
`app/tools/validation.py` — `validate_application()`

Category:
DETERMINISTIC

Inputs:
- `application: OnboardingApplication` — the full application object

Outputs:
- `ValidationResult` with:
  - `is_valid: bool`
  - `missing_fields: list[str]` — required fields that are None or empty
  - `invalid_fields: list[str]` — fields that exist but fail format validation
  - `errors: list[str]` — human-readable error descriptions

Side Effects:
None. Pure function.

Decision Authority:
No. Produces evidence only. The WorkerEngine decides what to do with the result.

Failure Modes:
None. This tool does not fail. It always returns a `ValidationResult`.

Confidence:
No. Returns boolean validity only.

Auditability:
The WorkerEngine records a `TOOL_EXECUTION` event with the validation result.

Worker Response:
- If `missing_fields` is non-empty: transition to `MISSING_INFORMATION` → `MORE_INFORMATION_REQUIRED`, set `final_decision = REQUEST_MORE_INFORMATION`.
- If `invalid_fields` is non-empty (but no missing fields): transition to `FAILED`, set `final_decision = REJECT_OR_BLOCK`.
- If `is_valid`: transition to `VERIFYING`.

Example:
```
Input: OnboardingApplication(applicant_name="Acme Corp", pan_number="INVALID", phone="9876543210")
Output: ValidationResult(is_valid=False, missing_fields=[], invalid_fields=["pan_number"], errors=["Invalid PAN format: INVALID"])
```

------------------------------------------------------------
Tool: File Validation
------------------------------------------------------------

Purpose:
Validate an uploaded file before it enters the processing pipeline. Checks emptiness, size limits, extension, and MIME type.

Module:
`app/tools/document_processing.py` — `validate_file()`

Category:
DETERMINISTIC

Inputs:
- `file_content: bytes` — raw file content
- `filename: str` — original filename (used for extension check)
- `content_type: str | None` — MIME type from upload
- `max_file_size: int` — configurable limit (default: 10MB)

Outputs:
- `FileValidationResult` with:
  - `valid: bool`
  - `error_code: str | None` — one of `EMPTY_FILE`, `FILE_TOO_LARGE`, `UNSUPPORTED_EXTENSION`, `UNSUPPORTED_MIME_TYPE`
  - `error_message: str | None`
  - `detected_mime: str | None`
  - `file_size: int`

Side Effects:
None. Pure function.

Decision Authority:
No. Used by the API route and document processing pipeline to reject files before storage.

Failure Modes:
None. Always returns a result.

Confidence:
No.

Auditability:
The API route records `DOCUMENT_VALIDATION_COMPLETED` when this is called via the upload endpoint.

Worker Response:
- If `valid` is False: return HTTP 400 to the client. Do not store or process the file.

Example:
```
Input: file_content=b"", filename="doc.pdf"
Output: FileValidationResult(valid=False, error_code="EMPTY_FILE", error_message="File is empty")
```

------------------------------------------------------------
Tool: OCR
------------------------------------------------------------

Purpose:
Extract text from image files using RapidOCR (ONNX-based, no GPU required, no system tesseract dependency).

Module:
`app/tools/ocr.py` — `run_ocr()`

Category:
DOCUMENT PROCESSING

Inputs:
- `image_path: str` — path to an image file (JPEG, PNG)

Outputs:
- `OCRResult` with:
  - `success: bool`
  - `raw_text: str` — all detected text joined by newlines
  - `lines: list[OCRLine]` — each line with text, confidence, and bounding box
  - `average_confidence: float` — mean confidence across all detected lines
  - `method: str` — always `"rapidocr"`
  - `error: str | None`

Side Effects:
None. Read-only operation on the image file.

Decision Authority:
No.

Failure Modes:
- No text detected in image → `success=False`, `error="No text detected in image"`
- Engine initialization failure → caught by broad exception handler
- Image file unreadable → caught by broad exception handler

Confidence:
Yes. `average_confidence` is the mean OCR confidence across all detected lines. This feeds into the overall document confidence calculation.

Auditability:
Not directly recorded. The document processing pipeline records `DOCUMENT_PROCESSING_STARTED` and `DOCUMENT_PROCESSING_COMPLETED` / `DOCUMENT_PROCESSING_FAILED` events that encompass OCR.

Worker Response:
- If `success` is False: the document processing pipeline returns a failed `DocumentProcessingResult` with `error_code="OCR_FAILED"`. The WorkerEngine retries if attempts remain.

Example:
```
Input: image_path="/data/uploads/app123/doc1.png"
Output: OCRResult(success=True, raw_text="Name: Ravi Kumar\nPAN: ABCDE1234F", average_confidence=0.92, method="rapidocr")
```

------------------------------------------------------------
Tool: PDF Processing
------------------------------------------------------------

Purpose:
Extract text from PDF files. Supports two paths: direct text extraction for text-based PDFs, and page-to-image rendering for scanned PDFs.

Module:
`app/tools/pdf_processing.py` — `extract_text_from_pdf()`, `render_pdf_pages()`

Category:
DOCUMENT PROCESSING

Inputs:
- `pdf_path: str` — path to the PDF file
- `max_pages: int` — maximum pages to render (default: 5, configurable)
- `dpi: int` — rendering resolution (default: 300)

Outputs:
- `PDFExtractionResult` with:
  - `success: bool`
  - `raw_text: str` — extracted text (empty for scanned PDFs on text extraction path)
  - `method: str` — `"pymupdf_text_extraction"` or `"pymupdf_render"`
  - `page_count: int`
  - `rendered_images: list[str]` — paths to rendered PNG images (render path only)
  - `error: str | None`
  - `is_scanned: bool`

Side Effects:
- `render_pdf_pages()` creates a temporary directory with rendered PNG images.
- Temp directory cleanup is NOT handled inside this function. The caller (`_process_pdf` in `document_processing.py`) handles cleanup via `try/finally` + `shutil.rmtree()`.

Decision Authority:
No.

Failure Modes:
- Corrupt PDF → PyMuPDF raises exception → `success=False`
- PDF with insufficient text (< 50 chars) → treated as scanned, returns `is_scanned=True`
- Rendering failure → `success=False`

Confidence:
No. Returns raw text or images. Confidence is calculated downstream.

Auditability:
Not directly recorded. Encompassed by document processing pipeline events.

Worker Response:
- If `success` is False on text extraction: the pipeline attempts rendering. If both fail, the document processing result has `error_code="PDF_EXTRACTION_FAILED"` or `PDF_RENDER_FAILED"`.

Example:
```
Input: pdf_path="/data/uploads/app123/certificate.pdf", max_pages=5
Output: PDFExtractionResult(success=True, raw_text="GST Certificate\nGSTIN: 27AABCU9603R1ZM", method="pymupdf_text_extraction", page_count=2, is_scanned=False)
```

------------------------------------------------------------
Tool: Structured Field Extraction
------------------------------------------------------------

Purpose:
Extract structured fields from raw OCR text using deterministic regex patterns and label-aware heuristics.

Module:
`app/tools/field_extraction.py` — `extract_fields()`

Category:
DETERMINISTIC

Inputs:
- `text: str` — raw text from OCR or PDF extraction

Outputs:
- `FieldExtractionResult` with:
  - `fields: dict[str, ExtractedField]` — each field with name, value, status, confidence, source_label
  - `overall_confidence: float` — mean confidence of successfully extracted fields
  - `fields_found: int` — count of fields with status `"extracted"`
  - `fields_attempted: int` — always 8

Side Effects:
None. Pure function.

Decision Authority:
No. Produces evidence only.

Failure Modes:
None. Always returns a result. If no fields are found, returns empty fields with zero confidence.

Confidence:
Yes. Each field has an individual confidence (0.0–1.0). Overall confidence is the mean of extracted field confidences.

Auditability:
Not directly recorded. Encompassed by document processing pipeline events.

Worker Response:
- Low overall confidence feeds into the document's `overall_confidence` score. If below threshold, triggers retry or escalation.

Fields Extracted (8 total):

| Field | Method | Confidence |
|-------|--------|------------|
| `pan_number` | Pattern `[A-Z]{5}[0-9]{4}[A-Z]` or label match | 0.95 / 0.85 |
| `gst_number` | Pattern `[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]` or label match | 0.95 / 0.85 |
| `phone` | Pattern `[6-9]\d{9}` or label match | 0.90 / 0.80 |
| `email` | Pattern `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | 0.95 |
| `date_of_birth` | Label patterns (`DOB:`, `Date of Birth:`, `Born:`) or bare date | 0.85 / 0.60 |
| `name` | Line-aware label match with known-label rejection | 0.85 |
| `address` | Multiline label-aware extraction | 0.70 |
| `registration_number` | Label patterns (`Registration No:`, `Certificate No:`) | 0.80 |

Example:
```
Input: text="Name: Ravi Kumar\nPAN: ABCDE1234F\nPhone: 9876543210"
Output: FieldExtractionResult(fields_found=3, overall_confidence=0.90, fields={"name": ExtractedField(value="Ravi Kumar", confidence=0.85), "pan_number": ExtractedField(value="ABCDE1234F", confidence=0.95), "phone": ExtractedField(value="9876543210", confidence=0.90)})
```

------------------------------------------------------------
Tool: Document Processing Pipeline
------------------------------------------------------------

Purpose:
Orchestrate the full document processing pipeline: file validation → storage → text extraction → field extraction → confidence calculation. This is the primary entry point for processing a document file.

Module:
`app/tools/document_processing.py` — `validate_file()`, `store_uploaded_file()`, `process_document_file()`

Category:
DOCUMENT PROCESSING

Inputs:
- `file_path: str` — path to stored file
- `document_type: str` — type label (e.g., "pan_card", "gst_certificate")
- `application_id: str`
- `document_id: str`
- `original_filename: str`
- `max_pdf_pages: int` — configurable (default: 5)

Outputs:
- `DocumentProcessingResult` with:
  - `document_id: str`
  - `application_id: str`
  - `document_type: str`
  - `original_filename: str`
  - `stored_path: str`
  - `processing_status: str` — `"completed"`, `"failed"`, or `"low_confidence"`
  - `raw_text: str`
  - `raw_text_available: bool`
  - `ocr_confidence: float`
  - `field_extraction_confidence: float`
  - `overall_confidence: float`
  - `extracted_fields: dict[str, Any]`
  - `processing_method: str` — `"rapidocr"`, `"pymupdf_text_extraction"`, `"rapidocr_on_rendered_pdf"`, or `"none"`
  - `error_code: str | None`
  - `error_message: str | None`
  - `attempt_count: int`
  - `created_at: str`
  - `processed_at: str`

Side Effects:
- Stores the file on disk (via `store_uploaded_file`)
- Creates per-application directories under `upload_dir`
- For scanned PDFs: creates and cleans up temp directories (try/finally)

Decision Authority:
No.

Pipeline:
```
1. Detect file extension
2. If PDF: extract text → if scanned, render pages → OCR each page
3. If image: OCR directly
4. Extract structured fields from text
5. Calculate overall confidence
6. Return result
```

Confidence Calculation:
```
overall = (ocr_confidence × 0.4) + (field_extraction_confidence × 0.4) + (min(fields_found / 4.0, 1.0) × 0.2)
```

Failure Modes:
- Empty file → `error_code="EMPTY_FILE"`
- File too large → `error_code="FILE_TOO_LARGE"`
- Unsupported extension → `error_code="UNSUPPORTED_EXTENSION"`
- OCR failure → `error_code="OCR_FAILED"`
- PDF text extraction failure → `error_code="PDF_EXTRACTION_FAILED"`
- PDF render failure → `error_code="PDF_RENDER_FAILED"`
- Unsupported file type (not PDF/image) → `error_code="UNSUPPORTED_FILE_TYPE"`

Auditability:
The API route records `DOCUMENT_UPLOAD_RECEIVED`, `DOCUMENT_VALIDATION_COMPLETED`, `DOCUMENT_PROCESSING_STARTED`, `DOCUMENT_PROCESSING_COMPLETED` or `DOCUMENT_PROCESSING_FAILED`.

Worker Response:
- If `processing_status` is `"failed"`: the extraction router returns zero-confidence data. The WorkerEngine retries if attempts remain.
- If `processing_status` is `"low_confidence"`: the result is used but may trigger escalation.

Example:
```
Input: file_path="/data/uploads/app123/pan.png", document_type="pan_card"
Output: DocumentProcessingResult(processing_status="completed", overall_confidence=0.87, processing_method="rapidocr", extracted_fields={"name": "Ravi Kumar", "pan_number": "ABCDE1234F"})
```

------------------------------------------------------------
Tool: Data Comparison
------------------------------------------------------------

Purpose:
Compare declared application information against verified document data, field by field, with normalization.

Module:
`app/tools/comparison.py` — `compare_information()`

Category:
DETERMINISTIC

Inputs:
- `application: OnboardingApplication` — the declared data
- `extracted_data: list[ExtractedDocumentData]` — verified data from documents

Outputs:
- `ComparisonResult` with:
  - `field_comparisons: dict[str, FieldComparison]` — per-field comparison
  - `overall_match: bool` — True if zero inconsistencies
  - `inconsistencies: list[str]` — human-readable mismatch descriptions

Side Effects:
None. Pure function.

Decision Authority:
No. Produces evidence only.

Compared Fields:
- `pan_number`
- `gst_number`
- `phone`
- `email`
- `address`

Normalization:
- All values are uppercased and stripped before comparison.
- Comparison is exact string match after normalization.

Confidence:
Per-field confidence: 1.0 if match, 0.5 if mismatch, 0.8 if field missing from application, 0.7 if field missing from document.

Auditability:
The WorkerEngine records a `COMPARISON` event with `overall_match` and `inconsistencies`.

Worker Response:
- The comparison result feeds into risk assessment and AI recommendation.
- Inconsistencies increase risk score.
- The WorkerEngine does not directly reject based on comparison alone; it feeds into downstream tools.

Example:
```
Input: application.pan_number="ABCDE1234F", extracted_data=[ExtractedDocumentData(extracted_fields={"pan_number": "ABCDE1234F"})]
Output: ComparisonResult(overall_match=True, inconsistencies=[])
```

------------------------------------------------------------
Tool: Risk Assessment
------------------------------------------------------------

Purpose:
Calculate a deterministic risk score based on verification results. No LLM involvement.

Module:
`app/tools/risk.py` — `assess_risk()`

Category:
DETERMINISTIC

Inputs:
- `comparison_result: ComparisonResult | None`
- `extracted_data: list[ExtractedDocumentData]`
- `application_metadata: dict[str, Any] | None`

Outputs:
- `RiskAssessment` with:
  - `risk_level: RiskLevel` — `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`
  - `risk_score: float` — 0.0 to 1.0
  - `risk_factors: list[str]`
  - `mitigation_suggestions: list[str]`

Side Effects:
None. Pure function.

Decision Authority:
No. Produces evidence only. However, the policy engine enforces CRITICAL risk as a hard block.

Scoring Rules (additive):
| Condition | Score Added |
|-----------|-------------|
| 1 data inconsistency | +0.30 |
| 2 data inconsistencies | +0.60 |
| 3+ data inconsistencies | +0.90 (capped at +0.90) |
| Low extraction confidence (<0.5) per document | +0.25 |
| No document data available | +0.30 |
| No PAN or GST verification | +0.15 |

Risk Level Thresholds:
| Score Range | Level |
|-------------|-------|
| 0.0 – 0.29 | LOW |
| 0.30 – 0.59 | MEDIUM |
| 0.60 – 0.79 | HIGH |
| 0.80 – 1.00 | CRITICAL |

Confidence:
No. Returns a score and level, not a confidence interval.

Auditability:
The WorkerEngine records a `TOOL_EXECUTION` event with the risk level, score, and factors.

Worker Response:
- CRITICAL risk → policy engine overrides any APPROVE recommendation to ESCALATE_TO_HUMAN.
- HIGH risk → rule-based recommendation escalates to human.
- Risk assessment feeds into the AI recommendation.

Example:
```
Input: comparison_result with 1 inconsistency, extracted_data with confidence 0.45
Output: RiskAssessment(risk_level=HIGH, risk_score=0.55, risk_factors=["1 data inconsistencies found", "Low extraction confidence (0.45) for pan_card"])
```

------------------------------------------------------------
Tool: AI Recommendation
------------------------------------------------------------

Purpose:
Generate a recommended action (APPROVE, REQUEST_MORE_INFORMATION, ESCALATE_TO_HUMAN, REJECT_OR_BLOCK) based on the full verification context.

Module:
`app/tools/llm_analysis.py` — `get_ai_recommendation()`

Category:
AI / PROBABILISTIC

Inputs:
- `context: WorkflowContext` — full workflow state including application, extracted data, comparison result, risk assessment

Outputs:
- `AIRecommendation` with:
  - `recommended_action: FinalDecision`
  - `confidence: float` — 0.0 to 1.0
  - `risk_level: RiskLevel`
  - `reason: str`
  - `evidence: list[str]`

Side Effects:
None.

Decision Authority:
No. This is an advisory recommendation. The policy engine (`_enforce_policy`) makes the final decision.

Two Execution Paths:

1. **Rule-based fallback** (default, used when no LLM API key is configured):
   - Missing fields → REQUEST_MORE_INFORMATION (confidence 0.9)
   - CRITICAL/HIGH risk → ESCALATE_TO_HUMAN (confidence 0.85)
   - 3+ inconsistencies → ESCALATE_TO_HUMAN (confidence 0.7)
   - 1–2 inconsistencies → REQUEST_MORE_INFORMATION (confidence 0.75)
   - Low extraction confidence → ESCALATE_TO_HUMAN (confidence 0.65)
   - No extracted document data → REQUEST_MORE_INFORMATION (confidence 0.9)
   - All checks pass with documents → APPROVE (confidence 0.8)

2. **LLM path** (optional, used when `llm_api_key` is configured):
   - Sends verification context to OpenRouter LLM endpoint
   - Parses structured JSON response
   - Falls back to rule-based on any failure (network, parse, timeout)

Failure Modes:
- No API key → uses rule-based fallback (not a failure)
- LLM network error → falls back to rule-based
- LLM returns malformed JSON → falls back to rule-based with ESCALATE_TO_HUMAN recommendation (confidence 0.3)
- LLM timeout (30s) → falls back to rule-based

Confidence:
Yes. Each recommendation includes a confidence score.

Auditability:
The WorkerEngine records an `AI_RECOMMENDATION` event with the recommended action, confidence, and reason.

Worker Response:
- The recommendation is fed to the policy engine, which may override it.
- If LLM is unavailable, the system continues with rule-based recommendations.

Example (rule-based):
```
Input: context with no missing fields, extracted documents, LOW risk, all data matching
Output: AIRecommendation(recommended_action=APPROVE, confidence=0.8, risk_level=LOW, reason="All verification checks passed")
```

------------------------------------------------------------
Tool: Extraction Router
------------------------------------------------------------

Purpose:
Route document extraction to the appropriate processing path. If a file path is available, uses the document processing pipeline. Otherwise falls back to LLM extraction or basic regex.

Module:
`app/tools/extraction.py` — `extract_document_data()`

Category:
DOCUMENT PROCESSING

Inputs:
- `document: ApplicationDocument` — document metadata
- `file_path: str | None` — path to stored file
- `application_id: str | None`

Outputs:
- `ExtractedDocumentData` with:
  - `document_id: str`
  - `document_type: str`
  - `extracted_fields: dict[str, Any]`
  - `confidence: float`
  - `extraction_method: str` — `"rapidocr"`, `"pymupdf_text_extraction"`, `"llm"`, or `"basic_regex"`
  - `raw_response: str | None`

Side Effects:
None directly. The downstream document processing pipeline may create temp files.

Decision Authority:
No.

Routing Logic:
```
1. If file_path and application_id are provided:
   → Use document processing pipeline (OCR + field extraction)
2. Else if document has raw_text:
   → Try LLM extraction
   → Fall back to basic regex extraction
3. Else:
   → Return zero-confidence empty result
```

Failure Modes:
- Document processing pipeline failure → falls back to LLM/regex
- LLM extraction failure → falls back to basic regex
- No content available → returns zero-confidence empty result

Confidence:
Yes. Inherited from the downstream extraction method.

Auditability:
Encompassed by document processing pipeline events and extraction events.

Worker Response:
- Low confidence results trigger retry or escalation in the WorkerEngine.

------------------------------------------------------------
Tool: Escalation
------------------------------------------------------------

Purpose:
Create an escalation record and optionally notify an external system via webhook.

Module:
`app/tools/escalation.py` — `create_escalation()`

Category:
ESCALATION

Inputs:
- `context: WorkflowContext` — full workflow context
- `reason: str` — human-readable escalation reason
- `additional_info: dict[str, Any] | None`

Outputs:
- `dict[str, Any]` — escalation record containing:
  - `application_id`
  - `reason`
  - `current_state`
  - `risk_level`
  - `risk_score`
  - `risk_factors`
  - `recommendation`
  - `retry_count`
  - `additional_info`

Side Effects:
- If `escalation_webhook_url` is configured: sends HTTP POST to the webhook endpoint.
- Logs the escalation event.

Decision Authority:
No. This tool creates records; it does not decide.

Failure Modes:
- Webhook HTTP failure → logged as error, escalation record still created locally
- Webhook timeout (10s) → logged as error, continues

Confidence:
No.

Auditability:
The WorkerEngine records an `ESCALATION` event. The escalation record is returned but not persisted to SQLite (it is a transient dict).

Worker Response:
- Called by the WorkerEngine when escalation is required.
- The engine transitions to `ESCALATED_TO_HUMAN` after calling this tool.

Example:
```
Input: context with application_id="app123", reason="All document extraction attempts failed"
Output: {"application_id": "app123", "reason": "All document extraction attempts failed", "current_state": "TOOL_FAILED", ...}
```

------------------------------------------------------------
Tool: Workflow Memory
------------------------------------------------------------

Purpose:
Persist the full workflow context to SQLite so that application state survives process restarts.

Module:
`app/memory/store.py` — `WorkflowMemory`

Category:
STATE / MEMORY

What It Stores:
- Full `WorkflowContext` serialized as JSON
- Current workflow state
- Final decision
- Created/updated timestamps

Persistence Mechanism:
SQLite via aiosqlite. Uses `INSERT ... ON CONFLICT ... DO UPDATE` (upsert) keyed on `application_id`.

Operations:
- `save(context)` — upsert workflow context
- `get(application_id)` — retrieve workflow context
- `exists(application_id)` — check existence
- `list_applications()` — list all with state and timestamps
- `delete(application_id)` — remove application and audit events
- `clear()` — remove all data

Across Process Restart:
Fully recoverable. The context is serialized to JSON and deserialized on retrieval. All fields (extracted_data, comparison_result, risk_assessment, recommendation, final_decision) are preserved.

Authority:
This is the authoritative source of workflow state. The WorkerEngine reads from and writes to this store on every transition.

Worker Response:
- The WorkerEngine calls `save()` on every state transition and `get()` for status queries.

------------------------------------------------------------
Tool: Document Store
------------------------------------------------------------

Purpose:
Persist document processing records to SQLite, enabling reuse of previously processed documents.

Module:
`app/memory/store.py` — `DocumentStore`

Category:
STATE / MEMORY

What It Stores:
- Document processing results (OCR text, extracted fields, confidence scores, processing method, error information)
- Per-document metadata (filename, stored path, processing status)

Persistence Mechanism:
SQLite via aiosqlite. Documents are stored via the API route's direct INSERT, not via this store class.

Operations:
- `get_documents_for_application(application_id)` — retrieve all document records
- `get_document(document_id)` — retrieve a single document record

Reuse Logic (in WorkerEngine):
```
1. Check DocumentStore for persisted results
2. If persisted record exists with processing_status="completed":
   → Use persisted result if confidence >= low_confidence_threshold
   → Skip re-processing
3. If no persisted record or insufficient confidence:
   → Run extraction pipeline
```

Why Reuse Matters:
- Cost reduction: avoids redundant OCR calls
- Latency reduction: cached results are returned instantly
- Consistency: same document always produces same result

Worker Response:
- The WorkerEngine checks for persisted results before running extraction. This is the primary mechanism for idempotent document processing.

------------------------------------------------------------
Tool: Database
------------------------------------------------------------

Purpose:
Manage the SQLite connection and schema for the entire application.

Module:
`app/memory/database.py` — `Database`, `init_database()`, `close_database()`

Category:
STATE / MEMORY

Schema (3 tables):

```sql
workflow_contexts (
    application_id TEXT PRIMARY KEY,
    context_json TEXT NOT NULL,
    current_state TEXT NOT NULL,
    final_decision TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)

audit_events (
    event_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    state TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'SAKSHAM',
    action TEXT NOT NULL,
    result TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
)

documents (
    document_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    raw_text TEXT,
    raw_text_available INTEGER,
    ocr_confidence REAL,
    field_extraction_confidence REAL,
    overall_confidence REAL,
    extracted_fields_json TEXT,
    processing_method TEXT,
    error_code TEXT,
    error_message TEXT,
    attempt_count INTEGER,
    created_at TEXT NOT NULL,
    processed_at TEXT NOT NULL
)
```

Indexes:
- `idx_audit_events_application_id`
- `idx_audit_events_timestamp`
- `idx_documents_application_id`

Across Process Restart:
Fully recoverable. SQLite database persists on disk. Connection is re-established on startup via `init_database()`.

Worker Response:
- Database initialization occurs during FastAPI lifespan startup.
- Database is closed during FastAPI lifespan shutdown.

------------------------------------------------------------
Tool: Audit Logger
------------------------------------------------------------

Purpose:
Record every significant action as an immutable audit event in SQLite.

Module:
`app/audit/logger.py` — `AuditLogger`

Category:
AUDIT / OBSERVABILITY

What It Stores:
- `event_id` (UUID)
- `application_id`
- `timestamp` (ISO 8601)
- `state` (WorkflowState)
- `event_type` (EventType)
- `actor` (default: "SAKSHAM")
- `action` (tool or operation name)
- `result` (SUCCESS, FAILED, etc.)
- `metadata_json` (arbitrary JSON)

Event Types (17):
| Event Type | When Recorded |
|------------|---------------|
| `INPUT_RECEIVED` | Application submitted |
| `STATE_TRANSITION` | Every state change |
| `TOOL_EXECUTION` | Validation, risk assessment |
| `EXTRACTION` | Document data extraction |
| `COMPARISON` | Field comparison |
| `AI_RECOMMENDATION` | LLM/rule-based recommendation |
| `POLICY_DECISION` | Policy enforcement |
| `RETRY` | Retry attempt |
| `FAILURE` | Tool failure |
| `ESCALATION` | Escalation created |
| `DOCUMENT_UPLOAD_RECEIVED` | File uploaded via API |
| `DOCUMENT_VALIDATION_COMPLETED` | File validation done |
| `DOCUMENT_PROCESSING_STARTED` | Document processing begins |
| `DOCUMENT_PROCESSING_COMPLETED` | Document processing succeeds |
| `DOCUMENT_PROCESSING_FAILED` | Document processing fails |
| `DOCUMENT_PROCESSING_REUSED` | Persisted result reused |
| `DOCUMENT_LOW_CONFIDENCE` | Document below confidence threshold |

Persistence Mechanism:
SQLite. Events are inserted and committed immediately.

Across Process Restart:
Fully recoverable. Events are persisted to SQLite.

Authority:
This is the authoritative audit trail. All events are immutable once written.

Worker Response:
- The WorkerEngine calls `_record_event()` after every significant action.
- Events are used for debugging, compliance, and workflow history queries.

---

# Tool Authority Model

Tools in Saksham have clearly defined authority levels. No tool operates autonomously. The WorkerEngine orchestrates all tool invocations and makes the final decision based on tool outputs.

## Observation Tools

Tools that gather or transform evidence. They do not decide approval, rejection, or escalation.

| Tool | What It Observes |
|------|------------------|
| OCR | Extracts text from images |
| PDF Processing | Extracts text or renders pages from PDFs |
| Structured Field Extraction | Extracts structured fields from raw text |
| Document Processing Pipeline | Orchestrates file validation, storage, extraction, confidence |

These tools produce data. They never decide what to do with that data.

## Deterministic Decision Tools

Tools that enforce objective validation or policy rules. They produce verdicts, not opinions.

| Tool | What It Decides |
|------|-----------------|
| Application Validation | Whether application fields are present and valid |
| File Validation | Whether uploaded file is acceptable |
| Data Comparison | Whether declared data matches verified data |
| Risk Assessment | What risk level the evidence implies |

These tools enforce rules. They do not have override authority.

## Probabilistic Reasoning

The AI Recommendation tool is the only probabilistic component. It is advisory.

**Current behavior:**
- When no LLM API key is configured (default): uses deterministic rule-based logic.
- When LLM API key is configured: calls OpenRouter LLM, falls back to rule-based on failure.

**The LLM recommendation is NOT authoritative over deterministic policy.**

Policy enforcement examples:
- LLM says APPROVE, but risk is CRITICAL → APPROVE does not happen. Policy escalates.
- LLM says APPROVE, but confidence is below threshold → APPROVE does not happen. Policy escalates.
- LLM says APPROVE, but no extracted documents exist → APPROVE does not happen. Policy requests more information.
- LLM says REJECT, but risk is LOW/MEDIUM → REJECT does not happen. Policy escalates (reject is blocked for non-critical risk).

The policy engine (`_enforce_policy`) is the final authority. The LLM informs but does not override.

## State Tools

WorkflowMemory and DocumentStore preserve the evidence and operational history. They are the authoritative source of truth for application state and document processing results.

## Audit Tools

AuditLogger records the complete operational history. Every action is recorded. If it was not logged, it did not happen.

## Escalation Tools

The Escalation tool terminates autonomous processing when required. It creates records and optionally notifies external systems. It does not decide to escalate; the WorkerEngine decides and calls this tool.

---

# Tool Orchestration Diagram

```
Application Submission
    │
    ▼
┌─────────────────────────┐
│ Application Validation   │ ← validate_application()
│ (DETERMINISTIC)          │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ Document Processing      │
│ Pipeline                 │
│ ┌─────────────────────┐ │
│ │ File Validation      │ │ ← validate_file()
│ │ (DETERMINISTIC)      │ │
│ └─────────┬───────────┘ │
│           ▼              │
│ ┌─────────────────────┐ │
│ │ File Storage         │ │ ← store_uploaded_file()
│ │ (STATE)              │ │
│ └─────────┬───────────┘ │
│           ▼              │
│ ┌─────────────────────┐ │
│ │ PDF Processing       │ │ ← extract_text_from_pdf()
│ │ or OCR               │ │    render_pdf_pages()
│ │ (DOC PROCESSING)     │ │    run_ocr()
│ └─────────┬───────────┘ │
│           ▼              │
│ ┌─────────────────────┐ │
│ │ Field Extraction     │ │ ← extract_fields()
│ │ (DETERMINISTIC)      │ │
│ └─────────┬───────────┘ │
│           ▼              │
│ ┌─────────────────────┐ │
│ │ Confidence Calc      │ │ ← _calculate_overall_confidence()
│ │ (DETERMINISTIC)      │ │
│ └─────────┬───────────┘ │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ Data Comparison          │ ← compare_information()
│ (DETERMINISTIC)          │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ Risk Assessment          │ ← assess_risk()
│ (DETERMINISTIC)          │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ AI Recommendation        │ ← get_ai_recommendation()
│ (AI / PROBABILISTIC)     │
│ [advisory only]          │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ Policy Enforcement       │ ← _enforce_policy()
│ (DETERMINISTIC)          │
│ [authoritative]          │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ Final Decision           │
├─────────────────────────┤
│ → APPROVED               │
│ → REQUEST_MORE_INFO      │
│ → ESCALATED_TO_HUMAN     │
│ → REJECTED               │
└─────────────────────────┘
```

At each step:
- **Information enters** as input from the previous step or from stored state.
- **Information leaves** as structured output (dataclass or Pydantic model).
- **Any step can fail** — failures propagate to the WorkerEngine for retry/escalation logic.
- **Any step can trigger escalation** — either directly (OCR failure after retries) or indirectly (risk assessment producing CRITICAL level).

---

# Tool Failure Contract

This section defines exactly what Saksham does when each failure scenario occurs.

## 1. OCR Fails

What happens:
- `run_ocr()` returns `OCRResult(success=False)`.
- The document processing pipeline returns `DocumentProcessingResult(processing_status="failed", error_code="OCR_FAILED")`.
- The extraction router returns `ExtractedDocumentData(confidence=0.0)`.
- The WorkerEngine's `_extract_with_retry()` increments `retry_count`, records `DOCUMENT_PROCESSING_FAILED` and `FAILURE` events.
- Transitions to `TOOL_RETRYING` → `VERIFYING` for next attempt.

After retry exhaustion:
- `_extract_with_retry()` returns `None`.
- If all documents fail: transitions to `TOOL_FAILED` → `ESCALATED_TO_HUMAN`.
- `final_decision = ESCALATE_TO_HUMAN`.
- Escalation record created with reason "All document extraction attempts failed".

Current behavior: **RETRY** with bounded count, then **ESCALATE**.

## 2. PDF Processing Fails

What happens:
- `extract_text_from_pdf()` returns `PDFExtractionResult(success=False)`.
- The pipeline returns `DocumentProcessingResult(processing_status="failed", error_code="PDF_EXTRACTION_FAILED")`.
- Same retry/escalation path as OCR failure.

If text extraction succeeds but returns scanned PDF:
- `render_pdf_pages()` is called.
- If rendering fails: `error_code="PDF_RENDER_FAILED"`.
- Same retry/escalation path.

If rendering succeeds but OCR on rendered pages fails:
- Returns `error_code="OCR_FAILED"`.
- Same retry/escalation path.

Current behavior: **RETRY** with bounded count, then **ESCALATE**.

## 3. Field Extraction Produces Low Confidence

What happens:
- `extract_fields()` returns low `overall_confidence`.
- The document's `overall_confidence` falls below `low_confidence_threshold` (0.6).
- The WorkerEngine detects low confidence after extraction.
- Records `DOCUMENT_LOW_CONFIDENCE` event.
- Increments `retry_count`, records `RETRY` event.
- Transitions to `TOOL_RETRYING` → `VERIFYING`.

After retry exhaustion:
- If still low confidence and `retry_count >= max_tool_retries`: transitions to `LOW_CONFIDENCE` → `ESCALATED_TO_HUMAN`.
- `final_decision = ESCALATE_TO_HUMAN`.

Current behavior: **RETRY** with bounded count, then **ESCALATE**.

## 4. Unsupported Document Format

What happens:
- `validate_file()` returns `valid=False` with error code `UNSUPPORTED_EXTENSION` or `UNSUPPORTED_MIME_TYPE`.
- The API route returns HTTP 400 to the client.
- The document is never stored or processed.

If an unsupported file type somehow reaches `process_document_file()`:
- Returns `DocumentProcessingResult(processing_status="failed", error_code="UNSUPPORTED_FILE_TYPE")`.
- Same retry/escalation path.

Current behavior: **REJECT** at the API boundary. If it bypasses validation, **RETRY** then **ESCALATE**.

## 5. Validation Fails

What happens:
- `validate_application()` returns `is_valid=False`.

If missing fields:
- `context.missing_fields` is populated.
- Transitions to `MISSING_INFORMATION` → `MORE_INFORMATION_REQUIRED`.
- `final_decision = REQUEST_MORE_INFORMATION`.
- Application is paused, waiting for resubmission.

If invalid fields (but no missing fields):
- Transitions to `FAILED`.
- `final_decision = REJECT_OR_BLOCK`.

Current behavior: **REQUEST MORE INFORMATION** (missing fields) or **REJECT** (invalid fields).

## 6. Comparison Finds Inconsistencies

What happens:
- `compare_information()` returns `overall_match=False`.
- Inconsistencies are recorded in the `COMPARISON` audit event.
- Risk score increases (0.3 per inconsistency, up to 3).
- The comparison result feeds into risk assessment and AI recommendation.

The system does NOT directly reject based on inconsistencies alone. The risk score and recommendation handle the response.

Current behavior: **CONTINUE** — evidence is recorded, downstream tools decide.

## 7. Risk Becomes Critical

What happens:
- `assess_risk()` returns `risk_level=CRITICAL`.
- The AI recommendation may still say APPROVE (if using LLM).
- The policy engine (`_enforce_policy`) checks: if risk is CRITICAL and recommendation is APPROVE → override to `ESCALATE_TO_HUMAN`.
- Logs warning: "Policy override: LLM recommended APPROVE for CRITICAL risk, escalating".

Current behavior: **ESCALATE** — CRITICAL risk blocks approval regardless of recommendation.

## 8. LLM Is Unavailable

What happens:
- `get_ai_recommendation()` checks `settings.llm_api_key`.
- If empty: logs warning "No LLM API key configured, using rule-based recommendation".
- Returns deterministic rule-based recommendation.

Current behavior: **FALLBACK** to rule-based. This is the default operating mode.

## 9. LLM Returns Malformed Output

What happens:
- `_parse_recommendation()` fails to parse JSON.
- Returns `AIRecommendation(recommended_action=ESCALATE_TO_HUMAN, confidence=0.3, risk_level=HIGH, reason="Failed to parse AI recommendation")`.
- The system escalates.

Current behavior: **FALLBACK** to safe default (escalate).

## 10. Persistence Fails

What happens:
- `WorkflowMemory.save()` fails (database connection lost, disk full, etc.).
- `PersistenceError` is raised with the `application_id`.
- The in-memory `updated_at` is rolled back to the previous value.
- The exception propagates to the WorkerEngine.
- The WorkerEngine logs the failure and re-raises.
- The API catches `PersistenceError` and returns HTTP 503 with structured error.

Current implementation: **CONTROLLED FAILURE**. State persistence failure is critical — the workflow cannot safely continue without durable state. The application receives HTTP 503 with `error_code="PERSISTENCE_FAILURE"`.

## 11. Audit Logging Fails

What happens:
- `AuditLogger.record()` fails.
- `AuditPersistenceError` is raised with `application_id` and `event_type`.
- The WorkerEngine's `_record_event()` catches `AuditPersistenceError`.
- The failure is logged via `logger.error()`.
- The workflow continues execution.

Current implementation: **GRACEFUL CONTINUATION**. Audit failure does NOT crash the workflow. The business decision was still made; only the audit trail is incomplete for that event. The failure is observable in logs.

## 12. Escalation Creation Fails

What happens:
- `create_escalation()` is called.
- If webhook fails: the exception is caught internally, logged as error, and the escalation record is still returned.
- The escalation record is created locally regardless of webhook success.

Current behavior: **CONTINUE** — webhook failure does not prevent escalation. The record is created locally.

---

# Retry Contract

## What Is Retried

Document extraction is retried. Specifically, the `_extract_with_retry()` method retries the full extraction pipeline (OCR + field extraction) for a single document.

## Maximum Retry Count

Configured via `settings.max_tool_retries`. Default: **3**.

## What Constitutes a Failed Attempt

A failed attempt is either:
1. The extraction pipeline raises an exception, OR
2. The extraction succeeds but confidence is below `low_confidence_threshold` (0.6)

Both cases increment `retry_count` and record appropriate events.

## What Happens After Retry Exhaustion

After `max_tool_retries` attempts:
- `_extract_with_retry()` returns `None`.
- If all documents for an application fail: transitions to `TOOL_FAILED` → `ESCALATED_TO_HUMAN`.
- `final_decision = ESCALATE_TO_HUMAN`.
- Escalation record is created.

## Persisted Result Reuse

Before running extraction, the WorkerEngine checks `DocumentStore.get_documents_for_application()`:
- If a persisted record exists with `processing_status="completed"` and `overall_confidence >= low_confidence_threshold`:
  - The persisted result is reused.
  - Extraction is skipped.
  - A `DOCUMENT_PROCESSING_REUSED` event is recorded.
- If the persisted result has insufficient confidence:
  - Extraction is run normally.

This prevents redundant processing of the same document.

---

# Idempotency / Reuse

## Persisted Document Reuse

A previously processed document with sufficient confidence is reused rather than reprocessed.

**What identifies the document:** `document_id` (UUID) associated with an `application_id`.

**Status that qualifies for reuse:** `processing_status = "completed"`.

**Confidence condition:** `overall_confidence >= low_confidence_threshold` (default: 0.6).

**What happens when persisted result is insufficient:** The document is reprocessed through the full extraction pipeline.

**Why reuse matters:**
- **Cost reduction:** Avoids redundant OCR calls (RapidOCR runs on CPU, each call takes time).
- **Latency reduction:** Cached results are returned instantly without re-processing.
- **Consistency:** The same document always produces the same result, regardless of how many times it is submitted.

## Workflow Context Reuse

The `WorkflowMemory` upserts on `application_id`. Resubmitting the same application overwrites the previous context. This is by design — the latest submission is authoritative.

---

# Security / Safety Boundaries

## File-Level Constraints

| Constraint | Value | Enforced By |
|------------|-------|-------------|
| Maximum file size | 10 MB (`settings.max_file_size`) | `validate_file()` |
| Allowed MIME types | `image/jpeg`, `image/png`, `application/pdf` | `validate_file()` |
| Allowed extensions | `.jpg`, `.jpeg`, `.png`, `.pdf` | `validate_file()` |
| Empty file rejection | Yes | `validate_file()` |
| Maximum PDF pages | 5 (`settings.max_pdf_pages`) | `render_pdf_pages()` |

## System-Level Constraints

- No arbitrary external system modification — the only external call is the optional escalation webhook.
- No unrestricted LLM authority — LLM output is advisory; policy enforcement is authoritative.
- No fabricated fields — extraction tools only return fields found in the document text.
- No bypassing policy — CRITICAL risk always blocks approval, regardless of recommendation.
- Escalation when evidence is insufficient — low confidence or missing data triggers human review.

## Data Constraints

- PAN validation pattern: `^[A-Z]{5}[0-9]{4}[A-Z]$` (strict)
- GST validation pattern: `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$`
- Phone validation: Indian format, starts with [6-9], 10 digits
- Required fields: `applicant_name`, `business_name`, `pan_number`, `phone`

---

# LLM Tool Contract

## Input Context

The LLM receives:
- Application ID
- Current workflow state
- Missing fields
- Retry count
- Verification summary (comparison results, extraction confidence, extraction methods)
- Risk summary (risk level, score, factors)

## LLM Recommendation

The LLM returns a structured JSON response:
```json
{
  "recommended_action": "APPROVE" | "REQUEST_MORE_INFORMATION" | "ESCALATE_TO_HUMAN" | "REJECT_OR_BLOCK",
  "confidence": 0.0 to 1.0,
  "risk_level": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "reason": "string",
  "evidence": ["string"]
}
```

## Structured Parsing

The response is parsed via `_parse_recommendation()`. Markdown code blocks are stripped. JSON parsing errors trigger fallback.

## Validation

If parsing fails: returns a safe default recommendation (ESCALATE_TO_HUMAN, confidence 0.3, risk HIGH).

## Policy Enforcement

The LLM does NOT directly control the final decision. The policy engine enforces:

1. CRITICAL risk + APPROVE recommendation → override to ESCALATE_TO_HUMAN
2. Low confidence + APPROVE recommendation → override to ESCALATE_TO_HUMAN
3. Missing fields → override to REQUEST_MORE_INFORMATION
4. Max retries exceeded → override to ESCALATE_TO_HUMAN
5. REJECT_OR_BLOCK + non-CRITICAL risk → override to ESCALATE_TO_HUMAN

The LLM informs. The policy decides.

## Current vs Optional

**CURRENT (default):**
- Rule-based fallback is available and used when no LLM API key is configured.
- This is the primary operating mode.
- Deterministic, auditable, no external dependencies.

**OPTIONAL:**
- OpenRouter LLM path exists when `llm_api_key` is configured.
- Uses `meta-llama/llama-3.1-8b-instruct` model by default (configurable via `settings.llm_model`).
- Temperature: 0.2
- Max tokens: 800
- Timeout: 30 seconds
- Falls back to rule-based on any failure.

---

# Memory and Audit Tools

## WorkflowMemory

**What it stores:** Full `WorkflowContext` serialized as JSON, including application data, extracted data, comparison results, risk assessment, recommendation, final decision, retry count, and missing fields.

**Why it exists:** To provide a single source of truth for application state that survives process restarts.

**Persistence mechanism:** SQLite via aiosqlite. Upsert on `application_id`.

**Across process restart:** Fully recoverable. The context is serialized to JSON and deserialized on retrieval.

**How the worker uses it:** The WorkerEngine calls `save()` on every state transition and `get()` for status queries. The `OnboardingService` calls `get()` for API responses.

## DocumentStore

**What it stores:** Document processing records including OCR text, extracted fields, confidence scores, processing method, and error information.

**Why it exists:** To enable reuse of previously processed documents and avoid redundant OCR calls.

**Persistence mechanism:** SQLite via aiosqlite. Documents are inserted by the API route.

**Across process restart:** Fully recoverable.

**How the worker uses it:** The WorkerEngine checks for persisted results before running extraction. If a valid persisted result exists, extraction is skipped.

## AuditLogger

**What it stores:** Immutable audit events with event_id, application_id, timestamp, state, event_type, actor, action, result, and metadata.

**Why it exists:** To provide a complete, auditable history of every action taken by the system.

**Persistence mechanism:** SQLite via aiosqlite. Events are inserted and committed immediately.

**Across process restart:** Fully recoverable. Events are persisted to SQLite.

**How the worker uses it:** The WorkerEngine calls `_record_event()` after every significant action. Events are queried for workflow history and debugging.

Do not describe SQLite as "AI memory". It is persistent workflow state / operational memory.

---

# Tool Invariants

The following rules must be preserved by any future changes to the tool ecosystem:

1. **Extraction tools must not invent fields.** If a field is not present in the document text, extraction returns `status="not_present"` with `value=None`. No field is ever fabricated.

2. **LLM recommendations must not bypass policy.** The policy engine is the final authority. LLM output is advisory only.

3. **Failed document processing must not silently become successful.** If OCR fails, the result has `processing_status="failed"` and `overall_confidence=0.0`. There is no silent recovery.

4. **Retry counts must remain bounded.** The maximum retry count is configurable but always finite. The system must not loop indefinitely.

5. **High-confidence persisted results should not be unnecessarily reprocessed.** The DocumentStore reuse logic must be preserved to avoid redundant OCR calls.

6. **Important decisions must remain auditable.** Every state transition, tool invocation, and decision must produce an audit event.

7. **Tool failures must result in an explicit workflow outcome.** No tool failure can leave the application in an ambiguous state. The WorkerEngine must transition to a terminal or escalation state.

8. **Tools should have clearly defined input/output contracts.** Every tool accepts typed inputs and returns typed outputs. No tool accepts raw strings where structured data is appropriate.

9. **Deterministic safety checks must remain enforceable independently of LLM behavior.** The risk assessment, validation, and policy enforcement tools must function correctly regardless of whether an LLM is configured.

---

# Future Tool Candidates

The following tools are potential future additions. None are currently implemented.

- **Merchant notification tool** — Send email/SMS notifications to applicants about status changes. NOT CURRENTLY IMPLEMENTED.
- **Human review queue integration** — Push escalation records to a human review dashboard. NOT CURRENTLY IMPLEMENTED.
- **External KYC verification** — Call external KYC APIs (e.g., Aadhaar verification, bank account verification). NOT CURRENTLY IMPLEMENTED.
- **Sanctions screening** — Check applicant names against sanctions/PEP lists. NOT CURRENTLY IMPLEMENTED.
- **CRM integration** — Push approved applications to a CRM system. NOT CURRENTLY IMPLEMENTED.
- **Document expiry tracking** — Monitor document expiry dates and trigger re-verification. NOT CURRENTLY IMPLEMENTED.
- **Batch processing** — Process multiple applications in parallel. NOT CURRENTLY IMPLEMENTED.
- **Webhook retry logic** — Retry failed webhook deliveries with exponential backoff. NOT CURRENTLY IMPLEMENTED.
