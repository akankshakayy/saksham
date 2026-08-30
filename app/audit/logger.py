from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.audit.provenance import Interface, get_call_context
from app.memory.database import Database, get_database
from app.memory.errors import AuditPersistenceError
from app.models.domain import AuditEvent
from app.models.states import EventType, WorkflowState

logger = logging.getLogger(__name__)


class AuditLogger:
    """SQLite-backed audit event recorder.

    Persists every audit event to SQLite so that the full
    decision trail survives process restarts.
    """

    def __init__(self, db: Database | None = None) -> None:
        self._db = db

    def _get_db(self) -> Database:
        if self._db is not None:
            return self._db
        return get_database()

    async def record(
        self,
        application_id: str,
        state: WorkflowState,
        event_type: EventType,
        action: str,
        result: str,
        metadata: dict[str, Any] | None = None,
        actor: str = "SAKSHAM",
    ) -> AuditEvent:
        """Record an audit event to SQLite.

        On failure, raises AuditPersistenceError so the caller can decide
        whether to continue. The event object is still returned so the caller
        knows what was attempted.
        """
        merged_metadata = dict(metadata) if metadata else {}

        interface, tool_name = get_call_context()
        if interface is not None:
            merged_metadata["interface"] = interface.value
            if tool_name is not None:
                merged_metadata["tool"] = tool_name
            if interface == Interface.MCP and actor == "SAKSHAM":
                actor = "MCP_CLIENT"

        event = AuditEvent(
            application_id=application_id,
            state=state,
            event_type=event_type,
            action=action,
            result=result,
            metadata=merged_metadata,
            actor=actor,
        )

        db = self._get_db()
        try:
            await db.conn.execute(
                """
                INSERT INTO audit_events
                    (event_id, application_id, timestamp, state,
                     event_type, actor, action, result, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.application_id,
                    event.timestamp.isoformat(),
                    event.state.value,
                    event.event_type.value,
                    event.actor,
                    event.action,
                    event.result,
                    json.dumps(event.metadata),
                ),
            )
            await db.conn.commit()

            logger.info(
                "AUDIT [%s] app=%s state=%s action=%s result=%s",
                event_type.value,
                application_id,
                state.value,
                action,
                result,
            )
        except Exception as exc:
            logger.error(
                "AUDIT_PERSISTENCE_FAILED [%s] app=%s state=%s action=%s result=%s error=%s",
                event_type.value,
                application_id,
                state.value,
                action,
                result,
                exc,
            )
            raise AuditPersistenceError(
                f"Failed to persist audit event {event_type.value} for {application_id}: {exc}",
                application_id=application_id,
                event_type=event_type.value,
            ) from exc

        return event

    async def get_events_for_application(self, application_id: str) -> list[AuditEvent]:
        """Retrieve all audit events for an application in chronological order."""
        db = self._get_db()
        cursor = await db.conn.execute(
            """
            SELECT event_id, application_id, timestamp, state, event_type,
                   actor, action, result, metadata_json
            FROM audit_events
            WHERE application_id = ?
            ORDER BY timestamp ASC, rowid ASC
            """,
            (application_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_all_events(self) -> list[AuditEvent]:
        """Retrieve all audit events."""
        db = self._get_db()
        cursor = await db.conn.execute(
            """
            SELECT event_id, application_id, timestamp, state, event_type,
                   actor, action, result, metadata_json
            FROM audit_events
            ORDER BY timestamp ASC, rowid ASC
            """
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def clear(self) -> None:
        """Remove all audit events."""
        db = self._get_db()
        await db.conn.execute("DELETE FROM audit_events")
        await db.conn.commit()

    @staticmethod
    def _row_to_event(row: Any) -> AuditEvent:
        """Convert a database row to an AuditEvent."""
        metadata = json.loads(row["metadata_json"])
        return AuditEvent(
            event_id=row["event_id"],
            application_id=row["application_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            state=WorkflowState(row["state"]),
            event_type=EventType(row["event_type"]),
            actor=row["actor"],
            action=row["action"],
            result=row["result"],
            metadata=metadata,
        )
