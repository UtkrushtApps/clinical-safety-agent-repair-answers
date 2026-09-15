from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any
from uuid import UUID, uuid4

import psycopg


class AuditWriter:
    """Writes one correlated, privacy-minimized audit history per run."""

    SENSITIVE_KEYS = {"subject_id", "report_id", "source_report_id"}
    FREE_TEXT_KEYS = {"narrative", "note_text", "response_text", "question"}

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._salt = os.getenv("AUDIT_HASH_SALT", "clinical-agent-audit").encode()

    def _token(self, value: Any) -> str:
        digest = hashlib.sha256(self._salt + str(value).encode()).hexdigest()[:16]
        return f"sha256:{digest}"

    def _clean_text(self, value: str) -> str:
        value = re.sub(r"[\w.+-]+@[\w.-]+", "[email-redacted]", value)
        value = re.sub(r"\b\d{3}-\d{3}-\d{4}\b", "[identifier-redacted]", value)
        return value[:2000]

    def _sanitize(self, value: Any, key: str | None = None) -> Any:
        if key in self.SENSITIVE_KEYS:
            return self._token(value)
        if key in self.FREE_TEXT_KEYS and isinstance(value, str):
            return {"redacted": True, "length": len(value), "digest": self._token(value)}
        if isinstance(value, dict):
            return {str(k): self._sanitize(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in value]
        if isinstance(value, str):
            return self._clean_text(value)
        return value

    def record(
        self,
        run_id: UUID,
        agent_name: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        sanitized = self._sanitize(payload)
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, run_id, agent_name, event_type, payload
                    ) VALUES (%s,%s,%s,%s,%s::jsonb)
                    """,
                    (
                        uuid4(),
                        run_id,
                        agent_name,
                        event_type,
                        json.dumps(sanitized, default=str),
                    ),
                )
