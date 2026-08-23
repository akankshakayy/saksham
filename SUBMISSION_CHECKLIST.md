# Saksham — Submission Checklist

Evaluator-oriented readiness checklist for the Eko AI Worker evaluation.

---

## Core Requirements

- [x] Goal clearly defined
- [x] User clearly defined
- [x] System context defined
- [x] Inputs defined
- [x] Outputs defined
- [x] Autonomous decisions defined
- [x] Constraints defined
- [x] Human escalation defined

## Workflow & State Machine

- [x] Workflow state machine documented (15 states)
- [x] State transitions defined with validation
- [x] Terminal states identified (APPROVED, REJECTED, ESCALATED, ESCALATED_TO_HUMAN, FAILED)
- [x] Decision authority hierarchy documented (Policy > Validation > Risk > Comparison > LLM)

## Tools & Capabilities

- [x] Tool contracts documented (15 tools)
- [x] Each tool has purpose, inputs, outputs, failure modes
- [x] Deterministic tools identified
- [x] Probabilistic tools identified (LLM only)
- [x] Fallback paths documented

## Memory & State

- [x] Memory/state strategy documented (SQLite)
- [x] Retry strategy documented (bounded, max 3)
- [x] Failure handling documented (persistence, audit, OCR, LLM)
- [x] Document reuse/caching documented

## Audit & Observability

- [x] Audit trail documented (17 event types)
- [x] Every action produces audit event
- [x] Events immutable once written
- [x] Full history queryable per application

## Demonstrated Behaviors

- [x] Intentional failure demonstrated (corrupted document → escalation)
- [x] LLM authority explicitly bounded (policy override test)
- [x] Persistence demonstrated (SQLite-backed, survives restart)
- [x] Current autonomy documented (what Saksham can/cannot do)
- [x] Future roadmap documented

## Repository Quality

- [x] Tests passing (109 tests)
- [x] No secrets committed (only placeholders in .env.example)
- [x] Dependencies declared (pyproject.toml)
- [x] .gitignore configured (comprehensive)
- [x] README complete (27 sections)
- [x] Documentation consistent with implementation

## Demo Readiness

- [x] API smoke test passing (health endpoint)
- [x] OpenAPI schema loadable
- [x] Example API requests documented
- [x] Test fixtures available (synthetic PAN card, GST certificate)

---

## Test Count

**109 tests passing**

## Warning Count

**1 pre-existing third-party warning** (StarletteDeprecationWarning from FastAPI test client — not from Saksham code)

## Version Status

**v0.1.0** — Feature-complete prototype for evaluation

---

## What This Demonstrates

1. Saksham is an autonomous verification pipeline, not a chatbot
2. The LLM is one advisory input — policy rules override all recommendations
3. Every decision is auditable from submission to outcome
4. Failures are handled gracefully with bounded retries and controlled escalation
5. State is durable across process restarts via SQLite
6. The system can be inspected at any point to determine status and history
