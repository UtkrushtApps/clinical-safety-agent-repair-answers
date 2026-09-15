from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

LOGGER = logging.getLogger(__name__)


class ClinicalTools:
    MAX_EVIDENCE_ROWS = 100

    def __init__(
        self,
        database_url: str,
        timeout_ms: int = 4000,
        evidence_lookup_delay_ms: int = 6000,
    ) -> None:
        self.database_url = database_url
        self.timeout_ms = timeout_ms
        self.evidence_lookup_delay_ms = evidence_lookup_delay_ms
        self.registry: dict[str, Callable[..., Any]] = {
            "get_protocol": self.get_protocol,
            "get_subject_evidence": self.get_subject_evidence,
            "find_prior_events": self.find_prior_events,
            "register_intake_case": self.register_intake_case,
            "create_site_follow_up": self.create_site_follow_up,
            "compute_reporting_clock": self.compute_reporting_clock,
            "classify_seriousness": self.classify_seriousness,
        }

    def _query(self, sql: str, values: tuple[Any, ...]) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, values)
                return [dict(row) for row in cursor.fetchall()]

    def get_protocol(self, study_id: str, **_: Any) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM protocols WHERE study_id = %s", (study_id,))
        return rows[0] if rows else None

    def get_subject_evidence(
        self,
        study_id: str,
        subject_id: str,
        site_id: str,
        limit: int = 50,
        **_: Any,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), self.MAX_EVIDENCE_ROWS))
        scope = (study_id, site_id, subject_id, limit)
        self._query("SELECT pg_sleep(%s)", (self.evidence_lookup_delay_ms / 1000,))
        return {
            "visits": self._query(
                "SELECT * FROM visit_schedules WHERE study_id=%s AND site_id=%s AND subject_id=%s ORDER BY window_start DESC LIMIT %s",
                scope,
            ),
            "deviations": self._query(
                "SELECT * FROM deviation_reports WHERE study_id=%s AND site_id=%s AND subject_id=%s ORDER BY observed_at DESC LIMIT %s",
                scope,
            ),
            "queries": self._query(
                "SELECT * FROM site_queries WHERE study_id=%s AND site_id=%s AND subject_id=%s ORDER BY opened_at DESC LIMIT %s",
                scope,
            ),
            "notes": self._query(
                "SELECT * FROM monitor_notes WHERE study_id=%s AND site_id=%s AND subject_id=%s ORDER BY recorded_at DESC LIMIT %s",
                scope,
            ),
        }

    def find_prior_events(
        self,
        study_id: str,
        subject_id: str,
        event_term: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        if event_term:
            return self._query(
                "SELECT * FROM safety_events WHERE study_id=%s AND subject_id=%s AND event_term ILIKE %s ORDER BY received_at DESC LIMIT 50",
                (study_id, subject_id, event_term),
            )
        return self._query(
            "SELECT * FROM safety_events WHERE study_id=%s AND subject_id=%s ORDER BY received_at DESC LIMIT 50",
            (study_id, subject_id),
        )

    SERIOUSNESS_CATEGORIES = {
        "hospitalization": ("hospital", "admission", "admitted", "overnight", "emergency department", "emergency room", "inpatient"),
        "life_threatening": ("life-threatening", "life threatening", "fatal", "death", "died"),
        "medically_important": ("medically important", "intervention", "disability", "congenital", "persistent"),
    }
    UNSETTLED_TERMS = (
        "not yet", "not available", "unavailable", "not confirmed", "unclear",
        "rather than", "while the site", "low confidence", "no event term",
        "unverified", "not sure", "pending", "outstanding",
    )

    def classify_seriousness(
        self,
        study_id: str,
        narrative: str,
        subject_id: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Seriousness for the study's own criteria, with the evidence behind it."""
        protocol = self.get_protocol(study_id) or {}
        criteria = str(protocol.get("reporting_notes", ""))
        text = (narrative or "").lower()
        categories = sorted(
            name
            for name, terms in self.SERIOUSNESS_CATEGORIES.items()
            if any(term in text for term in terms)
        )
        unsettled = [term for term in self.UNSETTLED_TERMS if term in text]
        prior = self.find_prior_events(study_id, subject_id) if subject_id else []
        if not text.strip() or (unsettled and not categories):
            seriousness = "uncertain"
        elif categories and unsettled:
            seriousness = "uncertain"
        elif categories:
            seriousness = "serious"
        else:
            seriousness = "non_serious"
        return {
            "study_id": study_id,
            "seriousness": seriousness,
            "categories": categories,
            "unsettled_evidence": unsettled,
            "prior_event_count": len(prior),
            "criteria_source": criteria[:400] or "protocol notes unavailable",
            "protocol_version": protocol.get("protocol_version"),
        }

    def route_to_queue(self, case_id: str, queue_key: str, reason: str) -> dict[str, Any]:
        """Place a case on one triage queue, once."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO queue_assignments (case_id, queue_key, reason)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (case_id) DO NOTHING
                    RETURNING queue_key, reason
                    """,
                    (case_id, queue_key, reason[:500]),
                )
                row = cursor.fetchone()
                if row:
                    return {**dict(row), "created": True}
                cursor.execute(
                    "SELECT queue_key, reason FROM queue_assignments WHERE case_id=%s",
                    (case_id,),
                )
                existing = cursor.fetchone()
                if not existing:
                    raise RuntimeError("queue assignment lookup failed")
                return {**dict(existing), "created": False}

    URGENT_TERMS = ("fatal", "death", "died", "life-threatening", "life threatening")

    def compute_reporting_clock(
        self,
        study_id: str,
        received_at: str,
        seriousness_text: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Reporting deadline from the study's own rule: day 0 is receipt, 7 calendar
        days for fatal or life-threatening events, 15 for every other serious event.
        Timezone is preserved so a report received late in the day keeps its date."""
        received = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        text = (seriousness_text or "").lower()
        urgent = any(term in text for term in self.URGENT_TERMS)
        days = 7 if urgent else 15
        protocol = self.get_protocol(study_id)
        return {
            "study_id": study_id,
            "day_zero": received.astimezone(timezone.utc).date().isoformat(),
            "due_by": (received + timedelta(days=days)).astimezone(timezone.utc).isoformat(),
            "rule": "fatal-or-life-threatening-7d" if urgent else "serious-15d",
            "rule_source": (protocol or {}).get("reporting_notes", "protocol notes unavailable"),
        }

    def register_intake_case(self, **arguments: Any) -> dict[str, Any]:
        required = ("source_report_id", "study_id", "site_id", "subject_id", "narrative")
        missing = [name for name in required if not arguments.get(name)]
        if missing:
            raise ValueError(f"missing required intake fields: {', '.join(missing)}")
        case_id = f"CASE-{uuid4().hex[:12].upper()}"
        received_at = arguments.get("received_at") or datetime.now(timezone.utc)
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO safety_events (
                        case_id, source_report_id, study_id, site_id, subject_id,
                        event_term, onset_at, seriousness_text, narrative, received_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (study_id, source_report_id) DO NOTHING
                    RETURNING case_id
                    """,
                    (
                        case_id,
                        arguments["source_report_id"],
                        arguments["study_id"],
                        arguments["site_id"],
                        arguments["subject_id"],
                        arguments.get("event_term") or "unclassified",
                        arguments.get("onset_at"),
                        arguments.get("seriousness_text") or "assessment pending",
                        arguments["narrative"],
                        received_at,
                    ),
                )
                row = cursor.fetchone()
                if row:
                    return {"case_id": row["case_id"], "created": True}
                cursor.execute(
                    "SELECT case_id FROM safety_events WHERE study_id=%s AND source_report_id=%s",
                    (arguments["study_id"], arguments["source_report_id"]),
                )
                existing = cursor.fetchone()
                if not existing:
                    raise RuntimeError("idempotent intake lookup failed")
                return {"case_id": existing["case_id"], "created": False}

    def create_site_follow_up(self, **arguments: Any) -> dict[str, Any]:
        required = ("source_report_id", "study_id", "site_id", "subject_id", "reason")
        missing = [name for name in required if not arguments.get(name)]
        if missing:
            raise ValueError(f"missing required follow-up fields: {', '.join(missing)}")
        normalized_reason = " ".join(str(arguments["reason"]).lower().split())[:500]
        material = "|".join(
            [arguments["study_id"], arguments["source_report_id"], normalized_reason]
        )
        dedupe_key = hashlib.sha256(material.encode()).hexdigest()
        work_id = uuid4()
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO follow_up_work (
                        work_id, source_report_id, study_id, site_id, subject_id,
                        reason, dedupe_key
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (dedupe_key) DO NOTHING
                    RETURNING work_id
                    """,
                    (
                        work_id,
                        arguments["source_report_id"],
                        arguments["study_id"],
                        arguments["site_id"],
                        arguments["subject_id"],
                        str(arguments["reason"])[:500],
                        dedupe_key,
                    ),
                )
                row = cursor.fetchone()
                if row:
                    return {"work_id": str(row["work_id"]), "created": True}
                cursor.execute(
                    "SELECT work_id FROM follow_up_work WHERE dedupe_key=%s",
                    (dedupe_key,),
                )
                existing = cursor.fetchone()
                return {"work_id": str(existing["work_id"]), "created": False}

    def ensure_physician_review(self, case_id: str, reason: str) -> dict[str, Any]:
        review_id = uuid4()
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO physician_review_work (review_id, case_id, reason)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (case_id) DO NOTHING
                    RETURNING review_id, status
                    """,
                    (review_id, case_id, reason[:1000]),
                )
                row = cursor.fetchone()
                if row:
                    return {"review_id": str(row["review_id"]), "status": row["status"], "created": True}
                cursor.execute(
                    "SELECT review_id, status, reviewer_role, reviewed_at FROM physician_review_work WHERE case_id=%s",
                    (case_id,),
                )
                existing = cursor.fetchone()
                if not existing:
                    raise RuntimeError("physician review lookup failed")
                return {**dict(existing), "review_id": str(existing["review_id"]), "created": False}

    def physician_review_completed(self, case_id: str) -> bool:
        rows = self._query(
            """
            SELECT 1 FROM physician_review_work
            WHERE case_id=%s AND status='completed'
              AND reviewer_role='physician' AND reviewed_at IS NOT NULL
            """,
            (case_id,),
        )
        return bool(rows)

    def save_disposition(
        self,
        case_id: str,
        run_id: Any,
        status: str,
        human_review_required: bool,
        evidence_quality: str,
        disposition: dict[str, Any],
    ) -> None:
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO case_dispositions (
                        case_id, run_id, status, human_review_required,
                        evidence_quality, disposition
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (case_id) DO UPDATE SET
                        run_id=EXCLUDED.run_id,
                        status=EXCLUDED.status,
                        human_review_required=EXCLUDED.human_review_required,
                        evidence_quality=EXCLUDED.evidence_quality,
                        disposition=EXCLUDED.disposition,
                        updated_at=NOW()
                    """,
                    (
                        case_id,
                        run_id,
                        status,
                        human_review_required,
                        evidence_quality,
                        json.dumps(disposition, default=str),
                    ),
                )

    def dispatch(
        self,
        name: str,
        arguments_json: str,
        *,
        context: Mapping[str, Any] | None = None,
        allowed_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        try:
            if name not in self.registry or (allowed_tools is not None and name not in allowed_tools):
                raise PermissionError(f"tool is not allowed: {name}")
            arguments = json.loads(arguments_json or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
            if context:
                for key in ("study_id", "site_id", "subject_id", "source_report_id"):
                    expected = context.get(key)
                    supplied = arguments.get(key)
                    if supplied is not None and expected is not None and supplied != expected:
                        raise PermissionError(f"{key} is outside the current report scope")
                    if expected is not None:
                        arguments[key] = expected
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.registry[name], **arguments)
                try:
                    result = future.result(timeout=self.timeout_ms / 1000)
                except FutureTimeout as exc:
                    raise TimeoutError(f"{name} exceeded {self.timeout_ms} ms") from exc
            return {
                "ok": True,
                "result": result,
                "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            }
        except Exception as exc:
            LOGGER.warning("Clinical tool %s failed: %s", name, exc)
            return {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            }
