# Saksham — Input / Output Examples

Saksham is evaluated not only by successful workflows, but also by how it behaves when information is missing, documents are unreadable, confidence is low, tools fail, or deterministic policy prevents autonomous approval.

The examples below demonstrate both successful autonomous execution and controlled failure/escalation.

## Legend

- **REAL** — Behavior directly exercised by the project's tests or manual verification.
- **ILLUSTRATIVE** — Behavior implemented by the system but presented as a policy/architecture demonstration, not a direct execution result.

---

# Example 1 — Successful Autonomous Verification

**Evidence:** `TestEndToEndApproved.test_approved_with_gst_document` (`tests/test_integration.py:288`)

## Scenario

A valid onboarding application is submitted with a GST certificate. Saksham processes the document, extracts fields, compares them against the application, assesses risk, generates a recommendation, enforces policy, and autonomously reaches an APPROVED decision.

## Input

```json
{
  "applicant_name": "Saksham Test Enterprises",
  "business_name": "Saksham Test Enterprises",
  "pan_number": "AABCT1234D",
  "gst_number": "27AABCT1234D1Z5",
  "phone": "9876543210",
  "email": "test@saksham.com",
  "documents": [
    {
      "document_id": "doc-gst-001",
      "document_type": "gst_certificate",
      "file_path": "<path to synthetic_gst_certificate.png>",
      "metadata": {"original_filename": "gst_cert.png"}
    }
  ]
}
```

## Processing

```
Application submitted
  ↓
VALIDATING — all required fields present, PAN format valid
  ↓
VERIFYING — document persisted to SQLite, extraction begins
  ↓
Document Processing — RapidOCR extracts text from GST certificate image
  ↓
Field Extraction — regex extracts: PAN, GST, phone, email
  ↓
Comparison — extracted fields match application fields (no inconsistencies)
  ↓
ANALYZING_RISK — risk score calculated (no inconsistencies, sufficient confidence)
  ↓
AI Recommendation — rule-based fallback: APPROVE (confidence 0.8)
  ↓
Policy Enforcement — no overrides triggered
  ↓
APPROVED
```

## Output

```json
{
  "application_id": "<generated uuid>",
  "current_state": "APPROVED",
  "final_decision": "APPROVE",
  "missing_fields": [],
  "retry_count": 0,
  "extracted_data": [
    {
      "document_id": "doc-gst-001",
      "document_type": "gst_certificate",
      "confidence": "> 0.5",
      "extraction_method": "rapidocr"
    }
  ],
  "comparison_result": {
    "overall_match": true,
    "inconsistencies": []
  },
  "risk_assessment": {
    "risk_level": "LOW",
    "risk_score": 0.0,
    "risk_factors": []
  },
  "recommendation": {
    "recommended_action": "APPROVE",
    "confidence": 0.8,
    "reason": "All verification checks passed"
  },
  "audit_events": ["INPUT_RECEIVED", "DOCUMENT_PROCESSING_COMPLETED", "EXTRACTION", "COMPARISON", "..."]
}
```

## Why This Is Autonomous

Saksham performed every step without human intervention: validated the input, ran OCR, extracted fields, compared data, assessed risk, generated a recommendation, enforced policy, and reached a final decision. The audit trail records every action.

**Evidence:** Test asserts `context.current_state == WorkflowState.APPROVED`, `context.final_decision == FinalDecision.APPROVE`, `ext.confidence > 0.5`, `ext.extraction_method == "rapidocr"`.

---

# Example 2 — Missing Information

**Evidence:** `test_missing_fields_triggers_more_info` (`tests/test_engine.py:52`)

## Scenario

An application is submitted with no required fields — no applicant name, no business name, no PAN, no phone. Saksham detects the missing information and requests it rather than escalating to a human.

## Input

```json
{
  "applicant_name": null,
  "business_name": null,
  "pan_number": null,
  "phone": null
}
```

## Processing

```
Application submitted
  ↓
VALIDATING — required fields check: applicant_name, business_name, pan_number, phone all missing
  ↓
MISSING_INFORMATION
  ↓
MORE_INFORMATION_REQUIRED
  ↓
final_decision = REQUEST_MORE_INFORMATION
```

## Output

```json
{
  "current_state": "MORE_INFORMATION_REQUIRED",
  "final_decision": "REQUEST_MORE_INFORMATION",
  "missing_fields": ["applicant_name", "business_name", "pan_number", "phone"]
}
```

## Why Saksham Does Not Escalate

Missing information is a recoverable situation. Saksham requests additional information instead of unnecessarily sending the case to a human reviewer. Escalation is reserved for cases where Saksham cannot safely proceed.

## Human Involvement

The applicant or operations team must provide the missing required fields and resubmit. Saksham will then re-validate and continue the workflow.

**Evidence:** Test asserts `context.current_state == WorkflowState.MORE_INFORMATION_REQUIRED`, `context.final_decision == FinalDecision.REQUEST_MORE_INFORMATION`, `len(context.missing_fields) > 0`.

---

# Example 3 — Corrupted Document / Intentional Failure

**Evidence:** `TestEndToEndEscalated.test_escalated_with_unreadable_document` (`tests/test_integration.py:334`)

## Scenario

This is the primary intentional failure scenario. A corrupted PNG file is submitted as a document. Saksham attempts to process it, retries on failure, exhausts retries, and escalates to a human.

## Input

```json
{
  "applicant_name": "Test User",
  "business_name": "Test Business",
  "pan_number": "ABCDE1234F",
  "phone": "9876543210",
  "documents": [
    {
      "document_id": "doc-fail-001",
      "document_type": "pan_card",
      "file_path": "<path to corrupted.png>",
      "metadata": {"original_filename": "corrupted.png"}
    }
  ]
}
```

The corrupted file contains a valid PNG header (`\x89PNG\r\n\x1a\n`) followed by 50 zero bytes — enough to pass file validation but not enough for OCR to produce meaningful output.

## Processing

```
Application submitted
  ↓
VALIDATING — passes (all required fields present, PAN valid)
  ↓
VERIFYING — document extraction begins
  ↓
Document Processing Attempt 1 — OCR fails on corrupted data
  ↓
TOOL_RETRYING → VERIFYING (retry_count = 1)
  ↓
Document Processing Attempt 2 — OCR fails again
  ↓
TOOL_RETRYING → VERIFYING (retry_count = 2)
  ↓
Document Processing Attempt 3 — OCR fails again
  ↓
retry_count (3) >= max_tool_retries (3) — retry exhausted
  ↓
TOOL_FAILED
  ↓
All document extraction attempts failed — escalation record created
  ↓
ESCALATED_TO_HUMAN
```

## Output

```json
{
  "current_state": "ESCALATED_TO_HUMAN",
  "final_decision": "ESCALATE_TO_HUMAN",
  "retry_count": 3,
  "audit_events": [
    "INPUT_RECEIVED",
    "DOCUMENT_PROCESSING_FAILED",
    "FAILURE",
    "RETRY",
    "DOCUMENT_PROCESSING_FAILED",
    "FAILURE",
    "RETRY",
    "DOCUMENT_PROCESSING_FAILED",
    "FAILURE",
    "ESCALATION",
    "STATE_TRANSITION"
  ]
}
```

## Why This Is Correct Behavior

Saksham must NOT:
- Retry forever
- Invent document information
- Approve without sufficient evidence
- Hide the failure

Instead, Saksham detects the failure, performs bounded retries (exactly 3), records every attempt and failure, and escalates to a human with full context. This is reliability, not weakness.

## Human Involvement

A human reviewer receives the escalated case with the full audit trail. They can investigate the corrupted document, request a replacement, or make a manual decision.

**Evidence:** Test asserts `context.current_state == WorkflowState.ESCALATED_TO_HUMAN`, `context.final_decision == FinalDecision.ESCALATE_TO_HUMAN`, and that `DOCUMENT_PROCESSING_FAILED` or `FAILURE` events exist in the audit trail.

---

# Example 4 — Low-Confidence Document

**Evidence:** `TestEndToEndLowConfidence.test_escalated_with_blank_image` (`tests/test_integration.py:402`)

## Scenario

A blank white image (100x100 pixels) is submitted as a PAN card document. The OCR processes it successfully but extracts no meaningful text, resulting in low confidence. After retries are exhausted, Saksham escalates.

**Key distinction:** This is different from Example 3 (corrupted document). Here the document technically processes — OCR runs, field extraction runs — but the result has insufficient confidence.

## Input

```json
{
  "applicant_name": "Test User",
  "business_name": "Test Business",
  "pan_number": "ABCDE1234F",
  "phone": "9876543210",
  "documents": [
    {
      "document_id": "doc-blank-001",
      "document_type": "pan_card",
      "file_path": "<path to blank.png>",
      "metadata": {"original_filename": "blank.png"}
    }
  ]
}
```

## Processing

```
Application submitted
  ↓
VALIDATING — passes
  ↓
VERIFYING — document extraction begins
  ↓
OCR on blank image — low confidence result (< 0.6 threshold)
  ↓
LOW_CONFIDENCE → retry
  ↓
OCR on blank image again — still low confidence
  ↓
LOW_CONFIDENCE → retry
  ↓
OCR on blank image again — still low confidence
  ↓
retry_count >= max_tool_retries
  ↓
LOW_CONFIDENCE
  ↓
ESCALATED_TO_HUMAN
```

## Output

```json
{
  "current_state": "ESCALATED_TO_HUMAN",
  "final_decision": "ESCALATE_TO_HUMAN",
  "audit_events_contain": ["LOW_CONFIDENCE", "RETRY", "ESCALATION"]
}
```

## Why the Confidence Threshold Matters

The `low_confidence_threshold` (default: 0.6) is the boundary between "Saksham can verify this" and "Saksham cannot verify this with sufficient certainty." A blank image produces OCR output, but no fields are extracted. The confidence score reflects this — Saksham knows it cannot verify the application based on this document.

**Evidence:** Test asserts `context.current_state` is either `ESCALATED_TO_HUMAN` or `LOW_CONFIDENCE`, and that `LOW_CONFIDENCE`, `FAILURE`, or `ESCALAT` events exist in the audit trail.

---

# Example 5 — Deterministic Policy Override (LLM Cannot Approve CRITICAL Risk)

**Evidence:** `test_llm_cannot_approve_critical_risk` (`tests/test_engine.py:148`)

## Scenario

The LLM recommends APPROVE, but the risk assessment shows CRITICAL risk. The deterministic policy engine overrides the recommendation and escalates to a human. This test proves the LLM is not the final decision authority.

## Input

```json
{
  "applicant_name": "Saksham Test",
  "business_name": "Saksham Test Pvt Ltd",
  "pan_number": "AABCT1234D",
  "phone": "6111111111",
  "email": "wrong@example.com",
  "documents": [
    {
      "document_type": "pan_card",
      "raw_text": "Name: Saksham Test Pvt Ltd\nPAN: ABCDE1234F"
    }
  ]
}
```

Extracted document data (mocked OCR):
```json
{
  "pan_number": "ABCDE1234F",
  "phone": "9876543210",
  "email": "test@example.com"
}
```

Three mismatches: PAN, phone, email → risk_score = 0.9 → CRITICAL.

## Processing

```
Application submitted (pan=AABCT1234D, phone=6111111111, email=wrong@example.com)
  ↓
VALIDATING — passes (all required fields present, PAN format valid)
  ↓
VERIFYING — document extraction mocked to return PAN=ABCDE1234F, phone=9876543210, email=test@example.com
  ↓
COMPARISON — 3 inconsistencies: PAN mismatch, phone mismatch, email mismatch
  ↓
ANALYZING_RISK — risk_score = 0.3 × min(3, 3) = 0.9 → CRITICAL
  ↓
AI RECOMMENDATION — mocked to return APPROVE (confidence 0.9)
  ↓
Policy Enforcement:
  risk.risk_level == CRITICAL
  AND rec.recommended_action == APPROVE
  → OVERRIDE: return ESCALATE_TO_HUMAN
  ↓
APPLY_DECISION — ESCALATE_TO_HUMAN → state = ESCALATED
```

## Output

```json
{
  "current_state": "ESCALATED",
  "final_decision": "ESCALATE_TO_HUMAN",
  "risk_assessment": {
    "risk_level": "CRITICAL",
    "risk_score": 0.9,
    "risk_factors": ["3 data inconsistencies found between application and documents"]
  },
  "recommendation": {
    "recommended_action": "APPROVE",
    "confidence": 0.9,
    "reason": "All checks pass"
  },
  "audit_events": ["INPUT_RECEIVED", "...", "AI_RECOMMENDATION", "POLICY_DECISION"]
}
```

## Why This Matters

The LLM recommends, the policy decides. This is the core safety property. Even when the LLM explicitly returns APPROVE with high confidence, the deterministic policy engine overrides it when risk is CRITICAL. The decision authority hierarchy is:

1. **Policy rules** (highest authority — non-negotiable)
2. **Deterministic validation** (PAN format, required fields)
3. **Risk assessment** (additive scoring)
4. **Comparison results** (field-by-field matching)
5. **LLM recommendation** (advisory only)

**Evidence:** Test asserts `context.risk_assessment.risk_level == RiskLevel.CRITICAL`, `context.recommendation.recommended_action == FinalDecision.APPROVE`, `context.final_decision == FinalDecision.ESCALATE_TO_HUMAN`, `context.current_state == WorkflowState.ESCALATED`. Audit trail contains `POLICY_DECISION` event with `decision == "ESCALATE_TO_HUMAN"` and `AI_RECOMMENDATION` event with `recommended_action == "APPROVE"`.

---

# Example 6 — Persisted Document Reuse

**Evidence:** `TestPersistedDocumentReuse.test_reuses_persisted_result` (`tests/test_integration.py:443`)

## Scenario

A document is processed once and its extraction results are persisted in SQLite. When the same application is processed again, Saksham reuses the cached result instead of running OCR again.

## First Processing

```
Application with GST certificate submitted
  ↓
Document Store lookup — no persisted result found
  ↓
Full extraction pipeline: OCR → field extraction → confidence calculation
  ↓
Results persisted to SQLite (documents table)
  ↓
Application reaches APPROVED
```

## Subsequent Processing

```
Same application submitted again
  ↓
Document Store lookup — persisted result found (processing_status = "completed")
  ↓
Check confidence: overall_confidence >= low_confidence_threshold (0.6)
  ↓
DOCUMENT_PROCESSING_REUSED event recorded
  ↓
Extraction skipped — persisted data used directly
  ↓
Application reaches APPROVED (same result, no OCR repeated)
```

## Output

```json
{
  "current_state": "APPROVED",
  "final_decision": "APPROVE",
  "audit_events_contain": ["DOCUMENT_PROCESSING_REUSED"]
}
```

## Why This Design Matters

- **Reduces unnecessary processing** — OCR is CPU-intensive; cached results avoid repeated work.
- **Reduces latency** — Persisted results are returned instantly.
- **Reduces compute cost** — Aligned with Eko's cost-conscious philosophy.
- **Improves consistency** — Same document always produces same result.
- **Avoids repeated OCR** — No wasted effort on already-processed documents.

**Evidence:** Test asserts `context.current_state == WorkflowState.APPROVED`, `context.final_decision == FinalDecision.APPROVE`, and `"DOCUMENT_PROCESSING_REUSED" in event_types`.

---

# Example 7 — Process Restart / Durable Memory

**Evidence:** `test_persistence_across_restart_still_works` (`tests/test_reliability.py:268`), `test_full_workflow_persistence` (`tests/test_persistence.py:213`)

## Scenario

An application is processed by one engine instance. The database connection is closed (simulating a process restart). A new engine instance opens the same database and retrieves the complete state and audit history.

## Process A

```
Engine A processes application
  ↓
Workflow state persisted to SQLite
  ↓
Audit events persisted to SQLite
  ↓
Database closed (process A stops)
```

## Process B

```
Engine B starts
  ↓
Opens same SQLite database
  ↓
Retrieves application by ID — state restored
  ↓
Retrieves audit history — all events restored
  ↓
State matches exactly: same current_state, same final_decision
  ↓
Audit history matches exactly: same events, same event IDs
```

## Output

```json
{
  "process_a_state": "APPROVED",
  "process_b_state": "APPROVED",
  "state_match": true,
  "audit_event_count_match": true,
  "audit_event_ids_match": true
}
```

## Why This Matters

SQLite acts as durable operational memory for the prototype. Saksham's operational state is not limited to Python process memory. If the process crashes or restarts, the full workflow context and audit trail survive.

**Evidence:** Test asserts `ctx2.current_state == ctx1.current_state`, `len(events2) == len(events1)`, and event IDs match between instances.

---

# Example 8 — Database / State Persistence Failure

**Evidence:** `test_state_persistence_failure_raises_persistence_error` (`tests/test_reliability.py:56`), `test_api_returns_503_on_persistence_failure` (`tests/test_reliability.py:431`)

## Scenario

The database becomes unavailable during a state transition. Saksham detects the failure, rolls back the in-memory state, and returns a controlled error.

## Processing

```
Application submitted
  ↓
Engine attempts to persist initial workflow context
  ↓
Database write fails (SQLite unavailable, disk full, etc.)
  ↓
PersistenceError raised
  ↓
In-memory updated_at rolled back to previous value
  ↓
Error propagates to API layer
  ↓
HTTP 503 returned with structured error
```

## Output

```json
{
  "status_code": 503,
  "detail": {
    "error_code": "PERSISTENCE_FAILURE",
    "message": "Application could not be saved. Please try again."
  }
}
```

## Why This Is Correct

Saksham must never claim that a workflow state transition is durable when the database write failed. The safety principle is: **no false state claim**. The caller receives a clear, structured error and can retry at the application level.

**Evidence:** Test asserts `response.status_code == 503`, `detail["error_code"] == "PERSISTENCE_FAILURE"`, `"Application could not be saved" in detail["message"]`.

---

# Example 9 — Audit Persistence Failure

**Evidence:** `test_audit_persistence_failure_does_not_crash_workflow` (`tests/test_reliability.py:92`), `test_audit_failure_is_logged_but_workflow_completes` (`tests/test_reliability.py:387`)

## Scenario

The database is available for workflow state writes but fails on audit event writes. Saksham continues the workflow and logs the audit failure.

## Processing

```
Application submitted
  ↓
Workflow state persisted successfully
  ↓
Audit event recording attempted
  ↓
Audit write fails
  ↓
AuditPersistenceError raised
  ↓
Engine catches AuditPersistenceError — logs warning, continues
  ↓
Workflow completes normally
  ↓
Final decision returned to caller
```

## Output

```json
{
  "current_state": "APPROVED",
  "final_decision": "APPROVE",
  "audit_trail_incomplete": true,
  "logged_warning": "Audit persistence failed for app=<id> event=STATE_TRANSITION: ..."
}
```

## Why Audit Failure and State Failure Have Different Severity

- **State persistence failure (CRITICAL):** The workflow cannot safely continue without durable state. Raising an error prevents false state claims.
- **Audit persistence failure (IMPORTANT but non-critical):** The business decision was still made. The audit trail is incomplete, but the workflow outcome is valid. Crashing the workflow would lose the decision that was already reached.

**Evidence:** Test asserts `context.current_state in (WorkflowState.APPROVED, ...)`, `context.final_decision is not None`, and `"Audit persistence failed" in record.message`.

---

# Example 10 — Autonomous vs Human Boundary

**Evidence:** All rows verified against actual implementation.

| Situation | Saksham Action | Autonomous? | Human Required? |
|-----------|----------------|-------------|-----------------|
| Valid application with matching documents | Verify and approve | Yes | No |
| Missing required fields | Request more information | Yes | Only if unresolved |
| Valid document (OCR success, high confidence) | Extract and verify | Yes | No |
| Low-confidence document | Retry (bounded) | Yes | No initially |
| Retry exhaustion (3 failures) | Escalate | No | Yes |
| CRITICAL risk (score >= 0.8) | Block approval, escalate | No | Yes |
| Database persistence failure | Stop safely, return 503 | No | Operational intervention |
| Audit persistence failure | Log failure, continue workflow | Yes | Depends on policy |
| Corrupted file | Retry, then escalate | Partial | Yes (after escalation) |
| Invalid PAN format | Reject immediately | Yes | No |

---

# Example 11 — Complete Decision Trace

**Illustrative** — traces the full information chain Saksham uses before making a final decision.

## The Chain

```
INPUT
  applicant_name: "Saksham Test Enterprises"
  business_name: "Saksham Test Enterprises"
  pan_number: "AABCT1234D"
  gst_number: "27AABCT1234D1Z5"
  phone: "9876543210"
  email: "test@saksham.com"
  documents: [gst_certificate]
    ↓
VALIDATION RESULT
  is_valid: true
  missing_fields: []
  invalid_fields: []
    ↓
DOCUMENT EVIDENCE
  OCR extracted text from GST certificate
  Fields extracted: PAN, GST, phone, email
  processing_method: "rapidocr"
    ↓
EXTRACTION CONFIDENCE
  overall_confidence: > 0.5
  ocr_confidence: > 0.0
  field_extraction_confidence: > 0.0
    ↓
COMPARISON RESULT
  overall_match: true
  inconsistencies: []
  Extracted GST matches application GST
  Extracted phone matches application phone
    ↓
RISK RESULT
  risk_level: LOW
  risk_score: 0.0
  risk_factors: []
    ↓
AI RECOMMENDATION
  recommended_action: APPROVE
  confidence: 0.8
  reason: "All verification checks passed"
    ↓
POLICY EVALUATION
  CRITICAL risk? No → no override
  Low confidence? No → no override
  Missing fields? No → no override
  Retry exhausted? No → no override
  → recommendation stands
    ↓
FINAL DECISION
  final_decision: APPROVE
  current_state: APPROVED
    ↓
AUDIT TRAIL
  INPUT_RECEIVED → STATE_TRANSITION → TOOL_EXECUTION →
  DOCUMENT_PROCESSING_COMPLETED → EXTRACTION →
  COMPARISON → TOOL_EXECUTION → AI_RECOMMENDATION →
  POLICY_DECISION → STATE_TRANSITION
```

## Why This Makes Decisions Inspectable

This is not a black-box LLM response. Every piece of information in the decision chain is:
- **Persisted** in SQLite (workflow context + audit events)
- **Traceable** to specific tool invocations
- **Auditable** by human reviewers
- **Reproducible** from the same inputs

The evaluator can query any application's full history and reconstruct exactly why a decision was made.

---

## What These Examples Demonstrate

Saksham is not merely an LLM wrapper. The examples demonstrate:

- **Autonomous workflow execution** — 15-state machine drives the process from submission to decision
- **Deterministic validation** — Required field checks, PAN/GST format validation
- **Real document processing** — RapidOCR for images, PyMuPDF for PDFs, structured field extraction
- **Structured evidence extraction** — 8 regex-based fields extracted from document text
- **Risk assessment** — Additive scoring based on inconsistencies, confidence, and document availability
- **Policy enforcement** — Non-negotiable rules that override recommendations
- **Persistent state** — SQLite-backed workflow context survives process restarts
- **Document reuse** — Cached extraction results avoid redundant OCR
- **Bounded retries** — Exactly 3 attempts before escalation, never infinite
- **Human escalation** — Designed safety valve, not failure mode
- **Auditability** — Every action recorded with timestamps, actors, and outcomes
- **Controlled failure behavior** — PersistenceError with rollback, AuditPersistenceError with continuation

The important property is not that Saksham always succeeds. The important property is that when it cannot safely succeed, it fails in a bounded, observable, and controlled way.
