# Saksham Architecture

Saksham is a deterministic, rule-based autonomous onboarding verification worker built with Python 3.10+, FastAPI, SQLite (aiosqlite), RapidOCR, and PyMuPDF. It processes merchant/partner applications through a 15-state workflow, applying document processing, field extraction, risk assessment, and policy enforcement to reach auditable decisions—escalating to humans when it cannot safely resolve cases autonomously.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    External Clients                              │
│  HTTP API │ MCP Client │ Frontend (React+TypeScript+Vite)       │
└───────────────┬─────────────────────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FastAPI Application                            │
│  Routes: POST /applications │ GET /applications/{id}           │
│  MCP: /mcp/mcp (9 read-only tools, streamable-http)            │
└───────────────┬─────────────────────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                 WorkerEngine                                     │
│  State Machine: 15 states, 28 transitions, 5 terminal           │
│  Policy Engine: Safety > Validation > Risk > Comparison > LLM   │
│  Tools: 15 (validation, document_processing, ocr, etc.)         │
└───────────────┬─────────────────────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────────┐
│              Persistence Layer                                   │
│  SQLite: workflow_contexts │ documents │ audit_events            │
│  Filesystem: /data/uploads/{application_id}/                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Descriptions

### FastAPI (`app/main.py`, `app/api/routes.py`)

Synchronous REST API. Two entry points: `POST /applications` (full workflow), `POST /applications/{id}/documents` (pre-processing). No authentication (prototype). HTTP 400 for invalid input, HTTP 503 for persistence failures.

### WorkerEngine (`app/worker/engine.py`)

Core orchestrator. Drives workflow from submission to terminal state. Manages state transitions, invokes tools, handles retries, enforces policy. Executes synchronously within API request lifecycle.

### State Machine (`app/models/states.py`)

15 states, 28 valid transitions, 5 terminal states. Illegal transitions raise `ValueError`. Terminal states have empty transition sets. Single source of truth for allowed state changes.

### Document Pipeline (`app/tools/document_processing.py`)

Four-stage: **validate** → **store** → **extract** → **confidence**. Routes PDFs through text extraction or rendered-image OCR. Handles temp file cleanup via `try/finally`.

### MCP Interface (`app/mcp/server.py`)

9 read-only tools at `/mcp/mcp` via streamable-http. All access produces `MCP_ACCESS` audit events with caller provenance. Tools: `get_application_status`, `list_applications`, `get_application_documents`, `get_document`, `get_document_raw_text`, `get_audit_history`, `get_verification_summary`, `get_risk_assessment`, `validate_application`.

### Frontend (`frontend/`)

React + TypeScript + Vite SPA. Communicates via REST API. Provides application submission, status viewing, and audit history display.

---

## Trust Boundaries

### What CAN Modify Workflow State

- **WorkerEngine**: Orchestrates transitions
- **Policy Engine**: Overrides recommendations
- **FastAPI Routes**: Triggers workflow start

### What CANNOT Modify Workflow State

- **LLM**: Advisory only; policy overrides
- **MCP Clients**: Read-only tools
- **Frontend**: API-only interaction
- **Document Pipeline**: Produces evidence only
- **Risk Assessment**: Produces evidence only

### External Boundaries

- **LLM**: Cannot modify state; falls back to rule-based if unavailable
- **MCP**: Read-only; all access audited
- **API**: No authentication (prototype)
- **Database**: Single-instance SQLite; no horizontal scaling

---

## Data Flow

### Submission → Decision

```
1. POST /applications → WorkerEngine.process_application()
   → Create WorkflowContext → State: RECEIVED

2. VALIDATING → validate_application()
   → Check required fields, PAN/GST format → State: VERIFYING

3. VERIFYING → For each document:
   → Reuse if confidence ≥ 0.6 (skip OCR)
   → Otherwise: extract_document_data()
   → Retry up to 3 times on failure/low confidence
   → compare_information() → State: ANALYZING_RISK

4. ANALYZING_RISK → assess_risk() + get_ai_recommendation()
   → State: DECIDING

5. DECIDING → _enforce_policy() applies deterministic rules
   → State: APPROVED / REJECTED / ESCALATED

6. Terminal → Persist final state → No further transitions
```

### Escalation Path

```
Tool failure/low confidence → TOOL_RETRYING → TOOL_FAILED
  → ESCALATED_TO_HUMAN → Terminal

CRITICAL risk → Policy override → ESCALATED → Terminal
```

### Missing Information Path

```
Missing required fields → MISSING_INFORMATION
  → MORE_INFORMATION_REQUIRED → Application paused
```

---

## Key Invariants

### 1. Illegal State Transitions Are Rejected

`can_transition()` checks every transition against `VALID_TRANSITIONS`. Invalid transitions raise `ValueError`.

### 2. Terminal States Cannot Transition Further

All 5 terminal states have empty transition sets. Once reached, no further processing occurs.

### 3. Retry Counts Are Bounded

`max_tool_retries` (default: 3) limits attempts. No infinite loops or runaway compute.

### 4. Critical Risk Cannot Result in Approval

Policy engine overrides APPROVE to ESCALATE_TO_HUMAN when risk is CRITICAL.

### 5. Low-Confidence Evidence Cannot Silently Become High-Confidence

Confidence scores are calculated deterministically and persisted as-is. No component inflates scores.

### 6. Failed Processing Cannot Silently Become Successful

If OCR fails, result has `processing_status="failed"` and `overall_confidence=0.0`.

### 7. LLM Recommendations Cannot Bypass Policy

Policy engine is called after recommendation and can override it. LLM is advisory only.

---

## System Specifications

| Specification | Value |
|---------------|-------|
| Language | Python 3.10+ |
| Framework | FastAPI |
| Database | SQLite (aiosqlite) |
| OCR | RapidOCR (ONNX-based) |
| PDF Processing | PyMuPDF |
| Workflow States | 15 |
| Terminal Decisions | 5 |
| Audit Event Types | 18 |
| MCP Tools | 9 (read-only) |
| Required Fields | 4 (applicant_name, business_name, pan_number, phone) |
| Max File Size | 10 MB |
| Max PDF Pages | 5 |
| Low Confidence Threshold | 0.6 |
| High Risk Threshold | 0.8 |
| Max Tool Retries | 3 |
| Supported Types | JPEG, PNG, PDF |
| Tests | 216 passing |
