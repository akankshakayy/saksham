# Saksham — Eko Talking Points

## 1. What Saksham Is (and Isn't)

**Is:** An autonomous partner/merchant onboarding verification worker. It validates submissions, extracts evidence from documents via OCR, cross-checks data, assesses risk, and reaches a controlled decision — all without human intervention for clear-cut cases.

**Isn't:** A chatbot, a copilot, or a decision-support dashboard. It's a pipeline with a fixed state machine, bounded retries, and non-negotiable safety policies. Humans are involved only at the designed escalation boundary.

---

## 2. The 3 Key Innovations

### Deterministic Policy Engine

The LLM recommends. The policy decides. Five layers of authority, from highest to lowest:

1. **Policy rules** — CRITICAL risk always escalates, never approves. Non-negotiable.
2. **Deterministic validation** — PAN format regex, required field checks. No LLM needed.
3. **Risk assessment** — Additive scoring (0.0–1.0). No randomization, no hallucination.
4. **Comparison results** — Field-by-field matching between application and document evidence.
5. **LLM recommendation** — Advisory input only. Overridden by any higher layer.

If the LLM says APPROVE but risk is CRITICAL, the policy escalates. Always.

### Bounded Retries

- Exactly 3 attempts per document extraction. Not 2, not 4, not "until it works."
- Every retry logged with attempt number, confidence score, and failure reason.
- After 3 failures: escalation to human. No infinite loops, no silent degradation.

### Full Auditability

- 18 event types: STATE_TRANSITION, TOOL_EXECUTION, AI_RECOMMENDATION, POLICY_DECISION, RETRY, FAILURE, ESCALATION, EXTRACTION, COMPARISON, and 9 more.
- Every event has: UUID, application_id, timestamp, state, actor, action, result, structured metadata.
- Events are immutable once written to SQLite. If it wasn't logged, it didn't happen.
- MCP tool calls are also audited — actor is set to "MCP_CLIENT" for observability.

---

## 3. The LLM Is Advisory (Not Authoritative)

- When available: LLM generates a structured recommendation (action, confidence, risk_level, reason, evidence).
- When unavailable: Rule-based fallback produces equivalent output — same format, same decision path.
- The engine treats both identically. No conditional branching based on LLM presence.

**What the LLM can do:** Suggest APPROVE, REQUEST_MORE_INFORMATION, ESCALATE_TO_HUMAN, or REJECT_OR_BLOCK.

**What the LLM cannot do:**
- Override policy rules
- Modify workflow state
- Bypass retry limits
- Skip audit logging
- Persist its own decisions

The LLM has no memory, no state access, and no persistence. It receives context and returns a JSON object. That's the entire interface.

---

## 4. What We'd Build Next (With Production Infrastructure)

| Priority | Feature | Why |
|----------|---------|-----|
| 1 | External PAN/GST verification APIs | Validate against government databases |
| 2 | Authentication + authorization | Current API is open (prototype) |
| 3 | PostgreSQL + horizontal scaling | SQLite is single-process |
| 4 | Multi-document correlation | Cross-validate PAN vs GST |
| 5 | Webhook escalation delivery | Notify reviewers in real-time |
| 6 | ML-based risk scoring | Replace additive with predictive models |

---

## 5. Honest Limitations

| Limitation | Mitigation |
|-----------|------------|
| No authentication | Add OAuth2/API keys in production |
| No horizontal scaling | Migrate to PostgreSQL |
| No external verification | Integrate NSDL/GSTN APIs |
| No ML risk scoring | Replace with trained models |
| No multi-document correlation | Cross-document field matching |
| No webhook delivery | Add HTTP callback on escalation |

---

## 6. Technical Highlights

| Metric | Value |
|--------|-------|
| Tests | 109 passing |
| Event types | 18 |
| Workflow states | 15 |
| Terminal decisions | 4 (APPROVE, REQUEST_MORE_INFO, ESCALATE, REJECT) |
| Risk levels | 4 (LOW, MEDIUM, HIGH, CRITICAL) |
| Tools | 15 (validation, OCR, PDF, extraction, comparison, risk, LLM, escalation) |
| MCP tools | 9 (read-only, all audited) |
| Retry limit | 3 (bounded, configurable) |
| Thresholds | confidence: 0.6, risk: 0.8 |
| OCR | RapidOCR (ONNX, local) |
| PDF | PyMuPDF (text + image rendering) |
| Stack | FastAPI + aiosqlite + Python 3.10+ |
