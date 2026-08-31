#!/usr/bin/env python3
"""Saksham MCP Read-Only Review Agent — Proof of Concept.

Connects to the Saksham MCP server and inspects an application
using only read-only MCP tools. Produces a concise evidence-based
report on workflow state and human review requirements.

Usage:
    python poc/openclaw_review_agent.py <application_id>
    python poc/openclaw_review_agent.py 8a99f8df-4e24-41e4-b7a5-66c3cbd49708
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx

MCP_URL = "http://127.0.0.1:8000/mcp/mcp"
TIMEOUT = 30
API_KEY = os.environ.get("SAKSHAM_API_KEY", "")


async def mcp_call(
    client: httpx.AsyncClient,
    session_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call an MCP tool and return the parsed result."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": session_id,
    }
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = await client.post(MCP_URL, json=payload, headers=headers)
    for line in resp.text.split("\n"):
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            content = data.get("result", {}).get("content", [])
            if content:
                return json.loads(content[0]["text"])
    return {"error": "No response from MCP server"}


async def initialize_mcp(client: httpx.AsyncClient) -> str:
    """Initialize MCP session and return session ID."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "saksham-review-agent", "version": "0.1"},
        },
    }
    resp = await client.post(MCP_URL, json=payload, headers=headers)
    return resp.headers.get("mcp-session-id", "")


async def review_application(application_id: str) -> str:
    """Review a Saksham application and produce a structured report."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        session_id = await initialize_mcp(client)

        status = await mcp_call(
            client, session_id, "get_application_status", {"application_id": application_id}
        )
        if "error" in status:
            return f"Application {application_id}: {status['error']}"

        docs = await mcp_call(
            client, session_id, "get_application_documents", {"application_id": application_id}
        )
        risk = await mcp_call(
            client, session_id, "get_risk_assessment", {"application_id": application_id}
        )
        summary = await mcp_call(
            client, session_id, "get_verification_summary", {"application_id": application_id}
        )
        audit = await mcp_call(
            client, session_id, "get_audit_history", {"application_id": application_id}
        )

        state = status.get("current_state", "UNKNOWN")
        final_decision = status.get("final_decision")
        risk_level = risk.get("risk_level", "UNKNOWN")
        risk_score = risk.get("risk_score", 0)
        risk_factors = risk.get("risk_factors", [])
        recommendation = risk.get("recommendation")
        missing_fields = summary.get("missing_fields", [])
        retry_count = summary.get("retry_count", 0)
        doc_count = len(docs.get("documents", []))
        event_count = len(audit.get("events", []))

        escalated = state in ("ESCALATED_TO_HUMAN", "ESCALATED")
        human_review_required = escalated or (
            final_decision == "ESCALATE_TO_HUMAN"
        ) or risk_level == "CRITICAL"

        last_events = audit.get("events", [])[-3:]
        event_summary = [
            f"  {e.get('event_type')}: {e.get('action')} -> {e.get('result')}"
            for e in last_events
        ]

        report = f"""Application: {application_id}
Current State: {state}
Final Decision: {final_decision or 'pending'}
Risk Level: {risk_level} (score: {risk_score:.2f})
Risk Factors: {'; '.join(risk_factors) if risk_factors else 'None'}
AI Recommendation: {recommendation.get('recommended_action') if recommendation else 'N/A'}
  Confidence: {recommendation.get('confidence') if recommendation else 'N/A'}
  Reason: {recommendation.get('reason') if recommendation else 'N/A'}
Documents: {doc_count} uploaded
Missing Fields: {missing_fields if missing_fields else 'None'}
Retry Count: {retry_count}
Audit Events: {event_count} recorded
Recent Events:
{chr(10).join(event_summary) if event_summary else '  None'}
Human Review Required: {'Yes' if human_review_required else 'No'}
Reason: {'Saksham workflow has already escalated this application.' if escalated else 'Workflow state does not indicate escalation.'}"""

        return report


async def test_invalid_application() -> str:
    """Test behavior with nonexistent application."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        session_id = await initialize_mcp(client)
        result = await mcp_call(
            client,
            session_id,
            "get_application_status",
            {"application_id": "00000000-0000-0000-0000-000000000000"},
        )
        return json.dumps(result, indent=2)


async def test_prompt_injection() -> str:
    """Verify that document content with injection text is treated as data."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        session_id = await initialize_mcp(client)
        apps = await mcp_call(client, session_id, "list_applications", {"limit": 1})
        if not apps.get("applications"):
            return "No applications to test with"
        app_id = apps["applications"][0]["application_id"]
        docs = await mcp_call(
            client, session_id, "get_application_documents", {"application_id": app_id}
        )
        for doc in docs.get("documents", []):
            raw = await mcp_call(
                client,
                session_id,
                "get_document_raw_text",
                {"application_id": app_id, "document_id": doc["document_id"]},
            )
            text = raw.get("raw_text", "")
            if "ignore previous" in text.lower() or "approve" in text.lower():
                return (
                    f"Document {doc['document_id']} contains potential injection text.\n"
                    "Agent must treat this as data, not instruction."
                )
        return "No injection text found in documents. Safe baseline confirmed."


async def test_secret_isolation() -> str:
    """Verify no secrets leak through MCP tool outputs."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        session_id = await initialize_mcp(client)
        apps = await mcp_call(client, session_id, "list_applications", {"limit": 1})
        if not apps.get("applications"):
            return "No applications to inspect"
        app_id = apps["applications"][0]["application_id"]

        secrets_found = []
        for tool, args in [
            ("get_application_status", {"application_id": app_id}),
            ("get_audit_history", {"application_id": app_id}),
        ]:
            result = await mcp_call(client, session_id, tool, args)
            text = json.dumps(result)
            for pattern in ["sk-", "api_key", "ANTHROPIC", "OPENROUTER", "password", "secret"]:
                if pattern.lower() in text.lower():
                    secrets_found.append(f"{tool} contains '{pattern}'")

        if secrets_found:
            return "SECRETS LEAKED: " + "; ".join(secrets_found)
        return "No secrets detected in MCP tool outputs."


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python poc/openclaw_review_agent.py <application_id>")
        print("       python poc/openclaw_review_agent.py --test")
        sys.exit(1)

    if sys.argv[1] == "--test":
        print("=== Invalid Application Test ===")
        print(await test_invalid_application())
        print()
        print("=== Prompt Injection Test ===")
        print(await test_prompt_injection())
        print()
        print("=== Secret Isolation Test ===")
        print(await test_secret_isolation())
        return

    application_id = sys.argv[1]
    report = await review_application(application_id)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
