from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.memory.database import Database, get_database
from app.memory.errors import PersistenceError
from app.models.domain import WorkflowContext

logger = logging.getLogger(__name__)


def _serialize_context(context: WorkflowContext) -> str:
    """Serialize a WorkflowContext to JSON for storage."""
    return context.model_dump_json()


def _deserialize_context(row: Any) -> WorkflowContext:
    """Deserialize a WorkflowContext from a database row."""
    context_json = row["context_json"]
    return WorkflowContext.model_validate_json(context_json)


class WorkflowMemory:
    """SQLite-backed store for workflow contexts.

    Persists the full workflow context as JSON so that it can be
    reconstructed after process restart.
    """

    def __init__(self, db: Database | None = None) -> None:
        self._db = db

    def _get_db(self) -> Database:
        if self._db is not None:
            return self._db
        return get_database()

    async def save(self, context: WorkflowContext) -> None:
        """Persist a workflow context to SQLite.

        On failure, rolls back the in-memory updated_at and raises
        PersistenceError so the caller knows durable state was not written.
        """
        db = self._get_db()
        now = datetime.now(timezone.utc).isoformat()
        previous_updated_at = context.updated_at
        context.updated_at = datetime.now(timezone.utc)

        try:
            context_json = _serialize_context(context)
            current_state = context.current_state.value
            final_decision = context.final_decision.value if context.final_decision else None
            application_id = context.application.application_id

            await db.conn.execute(
                """
                INSERT INTO workflow_contexts
                    (application_id, context_json, current_state,
                     final_decision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(application_id) DO UPDATE SET
                    context_json = excluded.context_json,
                    current_state = excluded.current_state,
                    final_decision = excluded.final_decision,
                    updated_at = excluded.updated_at
                """,
                (
                    application_id,
                    context_json,
                    current_state,
                    final_decision,
                    context.created_at.isoformat(),
                    now,
                ),
            )
            await db.conn.commit()

            logger.info(
                "Saved workflow context for application %s in state %s",
                application_id,
                current_state,
            )
        except Exception as exc:
            context.updated_at = previous_updated_at
            raise PersistenceError(
                f"Failed to persist workflow context for "
                f"{context.application.application_id}: {exc}",
                application_id=context.application.application_id,
            ) from exc

    async def get(self, application_id: str) -> WorkflowContext | None:
        """Retrieve a workflow context by application ID."""
        db = self._get_db()
        cursor = await db.conn.execute(
            "SELECT context_json FROM workflow_contexts WHERE application_id = ?",
            (application_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _deserialize_context(row)

    async def exists(self, application_id: str) -> bool:
        """Check if an application exists in the store."""
        db = self._get_db()
        cursor = await db.conn.execute(
            "SELECT 1 FROM workflow_contexts WHERE application_id = ?",
            (application_id,),
        )
        return await cursor.fetchone() is not None

    async def list_applications(self) -> list[dict[str, Any]]:
        """List all applications with their current state."""
        db = self._get_db()
        cursor = await db.conn.execute(
            "SELECT application_id, current_state, final_decision, created_at, updated_at "
            "FROM workflow_contexts ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [
            {
                "application_id": row["application_id"],
                "current_state": row["current_state"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "final_decision": row["final_decision"],
            }
            for row in rows
        ]

    async def list_applications_paginated(
        self,
        *,
        state: str | None = None,
        risk_level: str | None = None,
        final_decision: str | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List applications with filtering, search, pagination, and total count.

        Returns (applications, total_count). Risk level, applicant name,
        business name, and risk score are extracted from context_json.
        Newest-first ordering.
        """
        db = self._get_db()

        base_query = (
            "SELECT application_id, current_state, final_decision, "
            "context_json, created_at, updated_at FROM workflow_contexts"
        )
        count_query = "SELECT COUNT(*) as cnt FROM workflow_contexts"
        params: list[Any] = []
        count_params: list[Any] = []
        conditions: list[str] = []

        if state:
            conditions.append("current_state = ?")
            params.append(state)
            count_params.append(state)
        if final_decision:
            conditions.append("final_decision = ?")
            params.append(final_decision)
            count_params.append(final_decision)
        if risk_level:
            conditions.append(
                "json_extract(context_json, '$.risk_assessment.risk_level') = ?"
            )
            params.append(risk_level)
            count_params.append(risk_level)
        if q:
            conditions.append(
                "("
                "json_extract(context_json, '$.application.applicant_name') LIKE ?"
                " OR json_extract(context_json, '$.application.business_name') LIKE ?"
                " OR application_id LIKE ?"
                ")"
            )
            like_term = f"%{q}%"
            params.extend([like_term, like_term, like_term])
            count_params.extend([like_term, like_term, like_term])

        where_clause = ""
        if conditions:
            where_clause = f" WHERE {' AND '.join(conditions)}"

        count_sql = count_query + where_clause
        cursor = await db.conn.execute(count_sql, count_params)
        total = (await cursor.fetchone())["cnt"]

        data_sql = base_query + where_clause + " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await db.conn.execute(data_sql, params)
        rows = await cursor.fetchall()

        applications = []
        for row in rows:
            applicant_name = None
            business_name = None
            risk_level_val = None
            risk_score_val = None
            try:
                ctx = json.loads(row["context_json"])
                applicant_name = ctx.get("application", {}).get("applicant_name")
                business_name = ctx.get("application", {}).get("business_name")
                risk_assessment = ctx.get("risk_assessment")
                if risk_assessment:
                    risk_level_val = risk_assessment.get("risk_level")
                    risk_score_val = risk_assessment.get("risk_score")
            except (json.JSONDecodeError, TypeError):
                pass

            applications.append(
                {
                    "application_id": row["application_id"],
                    "applicant_name": applicant_name,
                    "business_name": business_name,
                    "current_state": row["current_state"],
                    "final_decision": row["final_decision"],
                    "risk_level": risk_level_val,
                    "risk_score": risk_score_val,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )

        return applications, total

    async def delete(self, application_id: str) -> bool:
        """Delete an application and its audit events."""
        db = self._get_db()
        await db.conn.execute(
            "DELETE FROM audit_events WHERE application_id = ?",
            (application_id,),
        )
        cursor = await db.conn.execute(
            "DELETE FROM workflow_contexts WHERE application_id = ?",
            (application_id,),
        )
        await db.conn.commit()
        return cursor.rowcount > 0

    async def clear(self) -> None:
        """Remove all data. Use with caution."""
        db = self._get_db()
        await db.conn.execute("DELETE FROM audit_events")
        await db.conn.execute("DELETE FROM workflow_contexts")
        await db.conn.commit()


class DocumentStore:
    """SQLite-backed store for document processing records."""

    def __init__(self, db: Database | None = None) -> None:
        self._db = db

    def _get_db(self) -> Database:
        if self._db is not None:
            return self._db
        return get_database()

    async def get_documents_for_application(self, application_id: str) -> list[dict[str, Any]]:
        """Retrieve all persisted document records for an application."""
        db = self._get_db()
        cursor = await db.conn.execute(
            "SELECT * FROM documents WHERE application_id = ? ORDER BY created_at",
            (application_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            results.append(self._row_to_dict(row))
        return results

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        """Retrieve a single document record by ID."""
        db = self._get_db()
        cursor = await db.conn.execute(
            "SELECT * FROM documents WHERE document_id = ?",
            (document_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def get_document_for_application(
        self, application_id: str, document_id: str
    ) -> dict[str, Any] | None:
        """Retrieve a single document record scoped to an application."""
        db = self._get_db()
        cursor = await db.conn.execute(
            "SELECT * FROM documents WHERE document_id = ? AND application_id = ?",
            (document_id, application_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def save_document(self, result: Any) -> None:
        """Persist a document processing result to SQLite."""
        db = self._get_db()
        await db.conn.execute(
            """INSERT INTO documents
            (document_id, application_id, document_type, original_filename,
             stored_path, processing_status, raw_text, raw_text_available,
             ocr_confidence, field_extraction_confidence, overall_confidence,
             extracted_fields_json, processing_method, error_code, error_message,
             attempt_count, created_at, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.document_id,
                result.application_id,
                result.document_type,
                result.original_filename,
                result.stored_path,
                result.processing_status,
                result.raw_text,
                1 if result.raw_text_available else 0,
                result.ocr_confidence,
                result.field_extraction_confidence,
                result.overall_confidence,
                json.dumps(result.extracted_fields),
                result.processing_method,
                result.error_code,
                result.error_message,
                result.attempt_count,
                result.created_at,
                result.processed_at,
            ),
        )
        await db.conn.commit()

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a database row to a document dict."""
        return {
            "document_id": row["document_id"],
            "application_id": row["application_id"],
            "document_type": row["document_type"],
            "original_filename": row["original_filename"],
            "stored_path": row["stored_path"],
            "processing_status": row["processing_status"],
            "raw_text": row["raw_text"] or "",
            "raw_text_available": bool(row["raw_text_available"]),
            "ocr_confidence": row["ocr_confidence"],
            "field_extraction_confidence": row["field_extraction_confidence"],
            "overall_confidence": row["overall_confidence"],
            "extracted_fields_json": row["extracted_fields_json"] or "{}",
            "processing_method": row["processing_method"] or "",
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "attempt_count": row["attempt_count"],
            "created_at": row["created_at"],
            "processed_at": row["processed_at"],
        }
