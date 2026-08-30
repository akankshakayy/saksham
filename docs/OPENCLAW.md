# OpenClaw Integration Status

## Status Summary

OpenClaw can discover and invoke Saksham's MCP tools, but cannot complete a full agent turn. The MCP layer works end-to-end: tool listing, argument parsing, and read-only queries all return correct results. However, OpenClaw's agent runtime depends on an LLM provider (OpenRouter or Anthropic) to drive tool selection and response generation. With OpenRouter credits depleted and the Anthropic key invalid, no LLM turn completes. Saksham exposes only read-only tools — no mutation operations exist.

## What Works

- **MCP Tool Discovery**: `openclaw mcp probe` returns 9 Saksham tools (get_applications, get_application_by_id, get_documents, etc.)
- **MCP Tool Invocation**: Direct tool calls succeed via `openclaw mcp call` and Python MCP SDK
- **MCP Connectivity**: stdio transport connects to Saksham's FastAPI MCP server without issues
- **Read-Only Queries**: Application lists, document retrieval, audit logs — all functional

## What Doesn't Work

- **Full Agent Turn**: OpenClaw cannot complete an LLM reasoning step. No provider has valid credits/keys.
- **Autonomous Approvals**: Not possible. Saksham has no mutation tools (approve, reject, flag). The agent is read-only by design.
- **Voice/Chat Flow**: Requires an LLM turn to process user utterances and select tools.

## POC Script

`poc/openclaw_review_agent.py` — demonstrates MCP tool discovery and direct invocation without requiring an LLM provider.

## Configuration

Add to `~/.config/opencode/opencode.json`:

```json
{
  "mcpServers": {
    "saksham": {
      "command": "uvicorn",
      "args": ["app.main:app", "--port", "8000"],
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

Or connect via HTTP to `http://localhost:8000/mcp/mcp` when Saksham is running.

## How to Reproduce

1. Start Saksham: `uvicorn app.main:app --port 8000`
2. Probe tools: `openclaw mcp probe --server saksham`
3. Call a tool: `openclaw mcp call --server saksham --tool get_applications`
4. Attempt agent turn: `openclaw chat "show me pending applications"` — will fail at LLM provider

## Known Limitations

- Agent cannot reason over tool results (no LLM turn completes)
- Saksham exposes no write/mutation tools — agent is strictly observational
- OpenClaw agent persona ("Crestodian") and agent name ("main") are configured but non-functional without LLM access

## Future Path

- **Rescue**: OpenRouter credits or valid Anthropic key → agent can reason, select tools, and present results
- **Mutation Tools**: Add approve/reject/flag endpoints to Saksham MCP surface (requires policy engine integration)
- **Guardrails**: Any mutation tool must enforce state machine transitions — an agent must not bypass `WorkflowStateRules`
- **Audit**: Agent-initiated mutations must be logged to the audit trail with `performed_by: "openclaw_agent"`
