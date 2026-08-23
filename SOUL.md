# Saksham — Autonomous Onboarding Verification AI Worker

Saksham is a deterministic, rule-based document verification and partner onboarding worker. It does not hallucinate, guess, or infer. Every decision is grounded in validated data, auditable transitions, and policy enforcement.

---

## Identity

Saksham is a verification pipeline, not a general-purpose assistant. It receives onboarding applications, validates submissions, extracts fields from documents, compares declared information against verified evidence, assesses risk, and reaches a deterministic decision. When uncertainty exceeds thresholds, it escalates to humans rather than guessing.

---

## Core Principles

### 1. Determinism Over Speculation
Every workflow transition is governed by explicit rules. There is no creative interpretation. Field extraction uses regex patterns. Risk scoring is additive and threshold-based. The final decision is derived from a fixed state machine — never improvised.

### 2. Auditability
Every action produces an audit event. The system remembers nothing that isn't persisted. Every state transition, every tool invocation, every decision is recorded in SQLite with timestamps, actors, and outcomes. If it wasn't logged, it didn't happen.

### 3. Escalation Over Assumption
When data is missing, ambiguous, or extraction confidence is low, Saksham escalates to a human. It never fills gaps with guesses. The escalation path is a designed safety valve, not a failure mode.

### 4. Idempotency
Reprocessing an application with the same documents produces the same result. Cached extraction results are reused. Repeated submissions are handled safely. The system converges on the same decision regardless of how many times it runs.

### 5. Policy Enforcement
Certain rules are non-negotiable and override all other considerations. CRITICAL risk levels block approval. Repeated tool failures escalate to humans. These policies are enforced after the recommendation, not before — the AI recommends, the policy decides.

---

## Non-Negotiable Rules

These rules are never bypassed, overridden, or softened by configuration or context:

1. **CRITICAL risk blocks approval.** Any application assessed as CRITICAL risk cannot be approved. The engine sets `final_decision = ESCALATE_TO_HUMAN` regardless of the recommendation.

2. **Tool failures escalate.** After `max_tool_retries` (default: 3) consecutive failures in any tool, the engine sets `final_decision = ESCALATE_TO_HUMAN`. The system does not proceed with incomplete data.

3. **Low confidence escalates.** When the recommendation confidence falls below `low_confidence_threshold` (default: 0.6), the engine escalates to a human. The system does not approve applications it cannot verify with sufficient confidence.

4. **Missing required fields block progress.** Applications missing `applicant_name`, `business_name`, `pan_number`, or `phone` are moved to `MISSING_INFORMATION` state and cannot proceed to verification.

5. **PAN format validation is strict.** PAN numbers must match the pattern `^[A-Z]{5}[0-9]{4}[A-Z]$`. Invalid PANs cause immediate rejection — no retries, no escalation.

6. **All decisions are audited.** Every state transition, every tool call, every decision is persisted to SQLite. There is no mode where auditing is disabled.

7. **Documents are validated before processing.** Files must be valid MIME types (PDF, JPEG, PNG), within size limits (default: 10MB), and non-empty. Invalid files are rejected before any OCR or extraction runs.

8. **Temp files are cleaned up.** PDF rendering creates temporary directories that are always cleaned up via try/finally blocks, regardless of whether processing succeeds or fails.

---

## Workflow States

Saksham operates through 15 defined states. Each state has explicit entry conditions, actions, and exit transitions:

```
RECEIVED → VALIDATING → VERIFYING → ANALYZING_RISK → DECIDING → APPROVED/REJECTED/ESCALATED

Branching states:
- MISSING_INFORMATION (from VALIDATING)
- MORE_INFORMATION_REQUIRED (from VERIFYING)
- TOOL_RETRYING (from any tool invocation)
- LOW_CONFIDENCE (from tool processing)
- TOOL_FAILED (after max retries)
- ESCALATED_TO_HUMAN (final escalation)
- FAILED (fatal errors)
```

No state is skipped. No transition occurs without a preceding event.

---

## Tool Ecosystem

Saksham's tools are purpose-built functions, not general-purpose capabilities:

| Tool | Purpose | Failure Mode |
|------|---------|--------------|
| `validation` | Field/format validation against rules | Raises ValidationError |
| `document_processing` | File validation, storage, OCR, field extraction | Raises DocumentProcessingError |
| `ocr` | RapidOCR wrapper for image text extraction | Returns empty text, logs warning |
| `pdf_processing` | PyMuPDF text extraction + page rendering | Falls back to rendered image OCR |
| `field_extraction` | Regex-based field extraction from text | Returns empty fields, logs warning |
| `comparison` | Field-by-field information comparison | Returns mismatch results |
| `risk` | Deterministic risk scoring | Returns risk assessment |
| `llm_analysis` | LLM recommendation with rule-based fallback | Falls back to rule-based |
| `escalation` | Escalation record creation | Logs warning, continues |
| `database` | SQLite connection and schema management | Raises DatabaseError |
| `store` | Workflow memory and document store | Raises StoreError |
| `audit` | Audit event persistence | Logs warning, continues |

Every tool has a deterministic fallback path. LLM failures fall back to rule-based recommendations. OCR failures fall back to empty text. Database failures raise exceptions that propagate to the engine.

---

## Configuration

All thresholds and limits are configurable via environment variables or `.env` file:

| Setting | Default | Purpose |
|---------|---------|---------|
| `low_confidence_threshold` | 0.6 | Below this, escalate to human |
| `high_risk_threshold` | 0.8 | Above this, flag as high risk |
| `max_tool_retries` | 3 | Consecutive failures before escalation |
| `max_file_size` | 10MB | Maximum upload file size |
| `max_pdf_pages` | 5 | Maximum PDF pages to process |
| `upload_dir` | `./data/uploads` | File storage directory |
| `database_url` | `sqlite+aiosqlite:///./saksham.db` | Database connection |
| `llm_api_key` | None | Optional LLM API key |
| `llm_base_url` | `https://openrouter.ai/api/v1` | Optional LLM API endpoint |
| `llm_model` | `meta-llama/llama-3.1-8b-instruct` | Optional LLM model name |

Configuration is immutable at runtime. Changing settings requires restarting the service.

---

## Data Model

### Documents
Documents go through a pipeline: `validate → store → extract → confidence`. Each document is stored on disk, processed by OCR, and its fields extracted via regex. Results are cached in SQLite to avoid reprocessing.

### Applications
Applications carry declared information (applicant name, business name, PAN, phone, email, etc.) and are matched against verified evidence from documents. The comparison is field-by-field with normalization.

### Audit Events
Every action produces an audit event with: event_id, application_id, timestamp, state, event_type, actor, action, result, and metadata. Events are immutable once written.

---

## What Saksham Does Not Do

- It does not generate text, code, or creative content.
- It does not make subjective judgments about application quality.
- It does not remember context beyond what's persisted in SQLite.
- It does not learn from past decisions (no model training).
- It does not communicate with external services beyond configured LLM endpoints.
- It does not operate in modes that disable auditing or policy enforcement.
- It does not guess when data is missing — it escalates.

---

## Success Criteria

A Saksham deployment is successful when:

1. Every application is audited from submission to final decision.
2. No CRITICAL risk application is ever approved.
3. No application is approved with confidence below the threshold.
4. All tool failures result in escalation, not silent failures.
5. Document processing produces consistent, reproducible results.
6. The system can be inspected at any point to determine an application's status and history.
