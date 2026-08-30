# Saksham — Eko Demo Script (5-10 min)

## 1. Pre-Demo Setup (~1 min)

```bash
# Start the server
cd /home/cat/saksham
uvicorn app.main:app --reload --port 8000

# In another terminal, verify health
curl http://localhost:8000/api/v1/health
# Expected: {"status":"ok","version":"0.1.0"}

# Generate synthetic test documents if needed
python tests/create_fixtures.py
```

---

## 2. Demo Walk (~6 min)

### Step 1: Submit a Valid Application → APPROVED

```bash
curl -s -X POST http://localhost:8000/api/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "applicant_name": "Priya Sharma",
    "business_name": "Sharma Trading Co.",
    "pan_number": "ABCDE1234F",
    "gst_number": "27ABCDE1234F1Z5",
    "phone": "9876543210",
    "email": "priya@sharmatrading.com",
    "documents": [{
      "document_type": "gst_certificate",
      "raw_text": "GST Certificate\nName: Priya Sharma\nPAN: ABCDE1234F\nGSTIN: 27ABCDE1234F1Z5\nPhone: 9876543210\nEmail: priya@sharmatrading.com"
    }]
  }' | python3 -m json.tool
```

**Point out:** `state: APPROVED` — full pipeline executed autonomously: validation → document extraction → comparison → risk assessment → policy enforcement → decision.

```bash
# Get the application_id from the response above, then:
curl -s http://localhost:8000/api/v1/applications/{APP_ID} | python3 -m json.tool
```

**Show:** final_decision: APPROVE, risk_level: LOW, risk_score: 0.0, no missing fields.

---

### Step 2: Submit an Application with Mismatched Data → ESCALATED

```bash
curl -s -X POST http://localhost:8000/api/v1/applications \
  -H "Content-Type: application/json" \
  -d '{
    "applicant_name": "Rahul Verma",
    "business_name": "Verma Enterprises",
    "pan_number": "FGHIJ5678K",
    "phone": "9123456789",
    "email": "rahul@vermaent.com",
    "documents": [{
      "document_type": "pan_card",
      "raw_text": "PAN Card\nName: Different Name\nPAN: XXXXX9999X\nPhone: 0000000000"
    }]
  }' | python3 -m json.tool
```

**Point out:** The document says "Different Name" but application says "Rahul Verma". The PAN and phone also don't match. Saksham detects these inconsistencies.

```bash
curl -s http://localhost:8000/api/v1/applications/{APP_ID_2} | python3 -m json.tool
```

**Show:** final_decision: ESCALATE_TO_HUMAN, risk_level: MEDIUM or HIGH, risk_factors list showing the mismatches. The LLM recommended escalation, and the policy engine confirmed it.

---

### Step 3: Show the Audit Trail

```bash
curl -s http://localhost:8000/api/v1/applications/{APP_ID_2}/history | python3 -m json.tool
```

**Walk through the events in order:**

1. `INPUT_RECEIVED` — application entered the system
2. `STATE_TRANSITION` — RECEIVED → VALIDATING
3. `TOOL_EXECUTION` — validate_application: SUCCESS
4. `STATE_TRANSITION` — VALIDATING → VERIFYING
5. `EXTRACTION` — document data extracted
6. `COMPARISON` — inconsistencies detected
7. `TOOL_EXECUTION` — assess_risk: risk scored
8. `AI_RECOMMENDATION` — LLM/rule-based recommendation generated
9. `POLICY_DECISION` — final decision enforced

**Key point:** Every action has a UUID, timestamp, state, event_type, actor, and structured metadata. If it wasn't logged, it didn't happen.

---

### Step 4: Show MCP Tools (if time permits, ~1 min)

```bash
# MCP endpoint is at /mcp/mcp — tools are read-only
# Show the list of available tools:
curl -s -X POST http://localhost:8000/mcp/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 -m json.tool
```

**Point out 9 read-only tools:** get_application_status, list_applications, get_application_documents, get_document, get_document_raw_text, get_audit_history, get_verification_summary, get_risk_assessment, validate_application.

**Key point:** MCP access is itself audited — every tool call logs an MCP_ACCESS event with the actor set to "MCP_CLIENT".

---

## 3. Key Talking Points (~2 min)

### The LLM Is Advisory, Not Authoritative

- LLM generates a recommendation with confidence and risk level
- When LLM is unavailable (no API key, timeout, parse failure), rule-based fallback produces equivalent output
- Policy engine **always** has final say — CRITICAL risk blocks approval even if LLM says APPROVE

### Policy Authority Hierarchy

```
1. Policy rules          (non-negotiable — highest authority)
2. Deterministic validation (PAN format, required fields)
3. Risk assessment        (additive scoring, no randomness)
4. Comparison results     (field-by-field matching)
5. LLM recommendation     (advisory only — lowest authority)
```

### Bounded Retries

- Exactly 3 attempts for document extraction before escalation
- No infinite loops, no retry-forever patterns
- Every retry is audited with attempt number and reason

### Full Auditability

- 18 event types covering every action
- 15 workflow states with validated transitions
- SQLite-persisted audit trail survives process restarts

---

## 4. Troubleshooting

| Issue | Fix |
|-------|-----|
| Server won't start | Check `pip install -e ".[dev]"` completed, check port 8000 isn't in use |
| Health check fails | Wait 5s for DB init, check `saksham.db` exists |
| Application returns 500 | Check server logs — usually a missing dependency or bad DB path |
| OCR returns low confidence | Expected for raw_text inputs — the demo uses inline text, not real images |
| LLM recommendation says "rule_based_fallback" | Normal — no LLM API key configured, rule-based path is working correctly |
| MCP endpoint returns empty | Ensure the MCP server initialized — check lifespan logs on startup |

---

## Quick Reference: Expected Outcomes

| Scenario | Final Decision | Risk Level | Key Evidence |
|----------|---------------|------------|--------------|
| Valid app + matching doc | APPROVED | LOW | No inconsistencies, high confidence |
| Mismatched data | ESCALATED | MEDIUM/HIGH | Data inconsistencies detected |
| Missing required fields | MORE_INFORMATION_REQUIRED | LOW | applicant_name/business_name/pan_number/phone missing |
| Corrupted document (3 retries) | ESCALATED | HIGH | All extraction attempts failed |
