from __future__ import annotations


class PersistenceError(Exception):
    """Raised when a durable state persistence operation fails."""

    def __init__(self, message: str, *, application_id: str | None = None) -> None:
        super().__init__(message)
        self.application_id = application_id


class AuditPersistenceError(Exception):
    """Raised when an audit event cannot be durably persisted.

    This is NOT a critical workflow failure. The business decision was still made.
    The audit trail is incomplete but the workflow can continue.
    """

    def __init__(
        self,
        message: str,
        *,
        application_id: str | None = None,
        event_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.application_id = application_id
        self.event_type = event_type
