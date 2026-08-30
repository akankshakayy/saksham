from __future__ import annotations

from contextvars import ContextVar
from enum import Enum


class Interface(str, Enum):
    """Interface through which an operation was initiated."""

    API = "API"
    MCP = "MCP"
    WORKER = "WORKER"
    SYSTEM = "SYSTEM"


# Call-scoped context variable. Set before a tool invocation,
# read by AuditLogger.record() to stamp provenance metadata.
# Cleared automatically when the async task ends.
_call_interface: ContextVar[Interface | None] = ContextVar("saksham_call_interface", default=None)

_call_tool: ContextVar[str | None] = ContextVar("saksham_call_tool", default=None)


def set_call_context(interface: Interface, tool: str | None = None) -> None:
    """Set the current call context (call-scoped, not global)."""
    _call_interface.set(interface)
    if tool is not None:
        _call_tool.set(tool)


def get_call_context() -> tuple[Interface | None, str | None]:
    """Return (interface, tool) for the current call, or (None, None)."""
    return _call_interface.get(), _call_tool.get()


def clear_call_context() -> None:
    """Explicitly clear the current call context."""
    _call_interface.set(None)
    _call_tool.set(None)
