# Saksham — Operational Contract

This document defines the operational contract for agents and developers working with the Saksham codebase.

---

## Quick Reference

| Item | Value |
|------|-------|
| Language | Python 3.10+ |
| Framework | FastAPI |
| Database | SQLite (aiosqlite) |
| OCR | RapidOCR (ONNX-based) |
| PDF | PyMuPDF (pymupdf) |
| Testing | pytest + pytest-asyncio |
| Linting | ruff |
| Package | pyproject.toml (setuptools) |

---

## Project Structure

```
saksham/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app with lifespan
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py              # REST endpoints
│   ├── audit/
│   │   ├── __init__.py
│   │   └── logger.py              # Audit event persistence
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py            # Pydantic Settings
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── database.py            # SQLite connection + schema
│   │   └── store.py               # WorkflowMemory + DocumentStore
│   ├── models/
│   │   ├── __init__.py
│   │   ├── domain.py              # Domain dataclasses
│   │   ├── schemas.py             # API request/response schemas
│   │   └── states.py              # State machine + enums
│   ├── services/
│   │   ├── __init__.py
│   │   └── onboarding.py          # Service layer
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── comparison.py          # Field comparison
│   │   ├── document_processing.py # Document pipeline
│   │   ├── escalation.py          # Escalation logic
│   │   ├── extraction.py          # Extraction routing
│   │   ├── field_extraction.py    # Regex field extraction
│   │   ├── llm_analysis.py        # LLM + rule-based recommendation
│   │   ├── ocr.py                 # RapidOCR wrapper
│   │   ├── pdf_processing.py      # PyMuPDF text + image extraction
│   │   ├── risk.py                # Risk scoring
│   │   └── validation.py          # Field/format validation
│   └── worker/
│       ├── __init__.py
│       └── engine.py              # Core workflow engine
├── tests/
│   ├── conftest.py                # Shared fixtures
│   ├── create_fixtures.py         # Test image generation
│   ├── fixtures/                  # Synthetic test documents
│   ├── test_api.py
│   ├── test_comparison.py
│   ├── test_document_processing.py
│   ├── test_engine.py
│   ├── test_integration.py        # End-to-end integration tests
│   ├── test_persistence.py
│   ├── test_risk.py
│   ├── test_states.py
│   └── test_validation.py
├── data/                          # Runtime SQLite database
├── uploads/                       # Uploaded document storage
├── pyproject.toml
├── SOUL.md                        # System identity document
└── AGENTS.md                      # This file
```

---

## Development Workflow

### Setup
```bash
# Install dependencies
pip install -e ".[dev]"

# Verify installation
python -c "import app; print('OK')"

# Run tests
pytest tests/ -q

# Lint
ruff check app/ tests/
ruff format app/ tests/ --check
```

### Running Tests
```bash
# All tests
pytest tests/ -q

# Specific test file
pytest tests/test_document_processing.py -q

# With verbose output
pytest tests/ -v

# Stop on first failure
pytest tests/ -x
```

### Code Style
- Line length: 100 characters
- Target: Python 3.10+
- Ruff rules: E, F, I, N, W, UP
- No comments unless requested
- Use type hints consistently
- Use dataclasses for domain models
- Use async/await for all I/O operations

---

## Key Modules

### WorkerEngine (`app/worker/engine.py`)
The core orchestrator. Manages workflow state transitions, tool invocations, and policy enforcement. Never modify transition logic without updating the state machine in `app/models/states.py`.

### State Machine (`app/models/states.py`)
Defines 15 workflow states, 4 final decisions, 4 risk levels, and 17 event types. Transition rules are enforced by `WorkflowStateRules`. Changes here affect all downstream behavior.

### Document Processing (`app/tools/document_processing.py`)
Pipeline: validate → store → extract → confidence. Routes PDFs through text extraction or rendered-image OCR. Handles temp file cleanup via try/finally.

### Field Extraction (`app/tools/field_extraction.py`)
Regex-based extraction for 8 fields: name, PAN, GST, phone, email, DOB, address, registration. Line-aware name extraction prevents cross-line greedy capture.

### Risk Assessment (`app/tools/risk.py`)
Deterministic, additive scoring. No randomization. No LLM involvement. Scores are bounded [0.0, 1.0] with configurable thresholds.

### LLM Analysis (`app/tools/llm_analysis.py`)
Optional LLM integration. Falls back to rule-based recommendation when LLM is unavailable or fails. The engine treats both paths identically.

---

## Important Implementation Details

### Document Store Reuse
`DocumentStore.get_processing_record()` checks for persisted results before running OCR. If a document has already been processed, the cached result is returned. This prevents duplicate processing.

### PDF Temp Cleanup
`_process_pdf()` uses `try/finally` with `shutil.rmtree()` to clean up temporary directories created during PDF page rendering. This runs regardless of processing success or failure.

### datetime.utcnow() Deprecation
The codebase uses `datetime.now(UTC)` with `from datetime import timezone, UTC` instead of the deprecated `datetime.utcnow()`.

### fitz Import
The codebase uses `import pymupdf as fitz` instead of the deprecated `import fitz` to avoid deprecation warnings.

### WorkerEngine Document Integration
`WorkerEngine._extract_with_retry()` passes `file_path` and `application_id` to `extract_document_data()` for real file processing. It also passes `applicant_name` and `pan_number` from application data for document_type inference.

---

## Test Patterns

### Integration Tests (`tests/test_integration.py`)
16 end-to-end tests covering complete verification workflows. Tests use synthetic documents and mock LLM responses. All tests run against SQLite in-memory databases.

### Document Processing Tests (`tests/test_document_processing.py`)
40+ tests covering the full document pipeline: validation, storage, OCR, field extraction, confidence calculation, and persisted result reuse.

### Engine Tests (`tests/test_engine.py`)
Tests for the core workflow engine, state transitions, retry logic, and policy enforcement.

---

## Common Tasks

### Adding a New Document Type
1. Add MIME type to `ALLOWED_MIME_TYPES` in `app/tools/document_processing.py`
2. Add extraction logic to `app/tools/field_extraction.py`
3. Add validation rules to `app/tools/validation.py`
4. Write tests in `tests/test_document_processing.py`

### Modifying Risk Scoring
1. Edit `app/tools/risk.py`
2. Update thresholds in `app/config/settings.py`
3. Run `pytest tests/test_risk.py -q`
4. Update integration tests if thresholds affect outcomes

### Adding a New Workflow State
1. Add state to `WorkflowState` enum in `app/models/states.py`
2. Add transition rules to `WorkflowStateRules`
3. Handle state in `WorkerEngine._decide()` in `app/worker/engine.py`
4. Add audit event type if needed
5. Write tests in `tests/test_states.py`

### Changing Database Schema
1. Edit schema in `app/memory/database.py`
2. Update all queries that reference changed tables
3. Run `pytest tests/test_persistence.py -q`
4. Verify migration path if production data exists

---

## Things That Will Break

- Changing `WorkflowState` enum values without updating all references
- Modifying `AuditEvent` fields without updating database schema
- Changing `ExtractedDocumentData` fields without updating field extraction and comparison
- Removing or renaming settings in `app/config/settings.py` without updating `.env.example`
- Changing the document processing pipeline order without updating all dependent tools
- Modifying the risk scoring formula without updating integration test expectations
- Changing SQLite schema without running full test suite

---

## Verification Checklist

After making changes:

1. `pytest tests/ -q` — all tests pass
2. `ruff check app/ tests/` — no lint errors
3. `ruff format app/ tests/ --check` — formatting correct
4. Check test count: should be 95+ passing
5. Check warnings: should be ≤1 (third-party StarletteDeprecationWarning)
6. Verify audit events are still being recorded
7. Verify document processing pipeline still handles edge cases
8. Verify escalation paths still trigger on failures
