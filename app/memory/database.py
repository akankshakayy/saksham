from __future__ import annotations

import logging
from urllib.parse import urlparse

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workflow_contexts (
    application_id TEXT PRIMARY KEY,
    context_json TEXT NOT NULL,
    current_state TEXT NOT NULL,
    final_decision TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    state TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'SAKSHAM',
    action TEXT NOT NULL,
    result TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (application_id) REFERENCES workflow_contexts(application_id)
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    raw_text TEXT DEFAULT '',
    raw_text_available INTEGER DEFAULT 0,
    ocr_confidence REAL DEFAULT 0.0,
    field_extraction_confidence REAL DEFAULT 0.0,
    overall_confidence REAL DEFAULT 0.0,
    extracted_fields_json TEXT DEFAULT '{}',
    processing_method TEXT DEFAULT '',
    error_code TEXT,
    error_message TEXT,
    attempt_count INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES workflow_contexts(application_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_events_application_id
    ON audit_events(application_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp
    ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_documents_application_id
    ON documents(application_id);
"""


def _extract_db_path(database_url: str) -> str:
    """Extract the file path from a sqlite+aiosqlite URL."""
    parsed = urlparse(database_url)
    path = parsed.path
    if path.startswith("/"):
        path = path[1:]
    return path


class Database:
    """SQLite database connection manager.

    Manages a single aiosqlite connection for the application lifetime.
    """

    def __init__(self, database_url: str) -> None:
        self._db_path = _extract_db_path(database_url)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open connection and create tables if needed."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        logger.info("Connected to SQLite database: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Closed SQLite database connection")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn


_db: Database | None = None


def get_database() -> Database:
    """Get the global database instance."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db


async def init_database(database_url: str) -> Database:
    """Initialize the global database connection."""
    global _db
    if _db is not None:
        return _db
    _db = Database(database_url)
    await _db.connect()
    return _db


async def close_database() -> None:
    """Close the global database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None


def reset_database() -> None:
    """Reset the global database reference (for testing)."""
    global _db
    _db = None
