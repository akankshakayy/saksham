# MCP Interface — Saksham

## 1. Overview

Saksham exposes a Model Context Protocol (MCP) server for read-only inspection of
onboarding verification data. All 9 tools are strictly non-mutating: they query the
SQLite store and return data without altering workflow state, audit history, or any
persisted records. This makes the MCP interface safe for external agents, dashboards,
and LLM-driven workflows.

Every MCP tool call is recorded via an `MCP_ACCESS` audit event with caller
provenance stamped as `actor="MCP_CLIENT"`.

## 2. Tools

| # | Tool | Purpose | Inputs | Outputs |
|---|------|---------|--------|---------|
| 1 | `get_application_status` | Full application status | `application_id` | Applicant details, state, risk, recommendation, timestamps |
| 2 | `get_verification_summary` | Compact verification overview | `application_id` | State, decision, risk level/score, missing fields, retry count |
| 3 | `get_audit_history` | Full audit trail | `application_id` | Chronological events: transitions, tool runs, recommendations, decisions |
| 4 | `list_applications` | List applications with filters | `state`, `risk_level`, `final_decision`, `limit`, `offset` | Paginated summaries with name, state, risk, timestamps |
| 5 | `get_document_processing` | Document processing results | `application_id`, `document_id` | Extracted fields, confidence, processing method, errors |
| 6 | `get_workflow_config` | Thresholds, states, transitions | _(none)_ | Current thresholds, valid states, transition rules |
| 7 | `get_risk_factors` | Detailed risk breakdown | `application_id` | Risk level, score, individual factors, AI recommendation |
| 8 | `get_decision_explanation` | Human-readable decision reasoning | `application_id` | Decision, rationale, contributing factors |
| 9 | `health_check` | System health status | _(none)_ | Database connectivity, service readiness |

All tools return `{"error": "..."}` if the requested resource is not found.

## 3. Endpoint & Transport

| Property | Value |
|----------|-------|
| URL | `http://127.0.0.1:8000/mcp/mcp` |
| Transport | `streamable-http` |
| Mount | `app.mount("/mcp", mcp_server.streamable_http_app())` in `app/main.py:48` |
| Server | `MCPServer(name="saksham")` via `app/mcp/server.py` |

The MCP server is created by `create_mcp_server()` and mounted on the FastAPI
application at startup. The streamable-HTTP transport handles session management
and message framing.

## 4. Caller Provenance

Every MCP tool call sets call-scoped context via `set_call_context(Interface.MCP, tool_name)`
before invoking business logic. This propagates through the audit pipeline:

1. **ContextVar capture** — `app/audit/provenance.py` stores `(Interface.MCP, tool_name)`
   in `ContextVar`s scoped to the current async task.
2. **Audit stamping** — `AuditLogger.record()` reads the context and stamps
   `actor="MCP_CLIENT"` on every audit event produced during the call.
3. **MCP_ACCESS event** — Each tool invocation emits an additional `MCP_ACCESS` event
   recording the tool name and result (`SUCCESS` or `NOT_FOUND`).

**Why it matters:** Provenance lets you distinguish human-initiated API actions from
agent-initiated MCP queries in the audit trail, enabling access control policies,
usage analytics, and forensic review.

## 5. Security Boundaries

### Read-Only by Design
No MCP tool mutates application state, triggers workflow transitions, or writes to
the database. The `validate_application` tool performs a dry-run validation without
persisting any changes.

### Secret Isolation
Tool outputs never expose API keys, LLM credentials, webhook URLs, or other
secrets. Sensitive configuration (e.g., `llm_api_key`, `escalation_webhook_url`)
is held in `app/config/settings.py` and never surfaced through MCP responses.

### Audit Completeness
Every MCP access — successful or failed — is recorded. Access attempts for
non-existent applications still emit `MCP_ACCESS` events with `result="NOT_FOUND"`,
ensuring no blind spots in the audit trail.

## 6. Configuration

### OpenClaw Example

```json
{
  "mcpServers": {
    "saksham": {
      "url": "http://127.0.0.1:8000/mcp/mcp",
      "transport": "streamable-http"
    }
  }
}
```

### Environment

No additional environment variables are required for MCP. The server inherits
the same `Settings` configuration as the REST API (`LLM_API_KEY`, `DATABASE_URL`,
thresholds, etc.).

## 7. Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/test_mcp.py` | 18 | Each tool: success path, not-found handling, input validation |
| `tests/test_mcp_provenance.py` | 22 | ContextVar propagation, actor stamping, MCP_ACCESS events, cross-interface isolation |
| **Total** | **40** | |

Tests run against SQLite in-memory databases with synthetic application data.
MCP tools are invoked via `MCPServer.call_tool()` — the same code path used in
production.
