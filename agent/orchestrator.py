from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agent.audit import AuditWriter
from agent.model_client import ModelClient
from agent.specialists import SpecialistAgent
from agent.state import IncidentRequest, RunState
from agent.tools import ClinicalTools

LOGGER = logging.getLogger(__name__)

SERIOUS_MARKERS = (
    "hospital", "admission", "admitted", "overnight", "emergency",
    "life-threatening", "death", "fatal", "medically significant", "syncope",
)
UNCERTAIN_MARKERS = (
    "uncertain", "unsure", "not confirmed", "unavailable", "missing",
    "outstanding", "pending", "conflict", "observation", "not yet",
    "not sure", "low confidence", "no event term", "call dropped",
)


class ClinicalAgentGraph:
    def __init__(
        self,
        model: ModelClient | None,
        tools: ClinicalTools,
        audit: AuditWriter,
    ) -> None:
        self.model = model
        self.tools = tools
        self.audit = audit
        self.agent_names = ("evidence", "safety", "site_operations")

    def describe(self) -> dict[str, Any]:
        return {
            "supervisor": "clinical_supervisor",
            "specialists": list(self.agent_names),
            "tools": sorted(self.tools.registry),
            "bounds": {"specialists": 3, "tool_rounds_per_specialist": 2},
        }

    @staticmethod
    def _load_json(content: str | None) -> dict[str, Any]:
        try:
            value = json.loads(content or "{}")
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _infer_event_term(narrative: str) -> str:
        text = narrative.lower()
        for term in ("syncope", "neutropenia", "fainted", "rash", "fever"):
            if term in text:
                return "syncope" if term == "fainted" else term
        return "unclassified"

    def _select_agents(self, incident: IncidentRequest) -> list[str]:
        requested: list[str] = []
        try:
            message = self.model.complete(
                [
                    {
                        "role": "system",
                        "content": "Select relevant specialists from evidence, safety, and site_operations. Reply only as JSON: {\"agents\": [...]}. Safety and evidence are mandatory for adverse-event intake.",
                    },
                    {"role": "user", "content": incident.model_dump_json()},
                ]
            )
            plan = self._load_json(message.content)
            if isinstance(plan.get("agents"), list):
                requested = [str(name) for name in plan["agents"]]
        except Exception:
            LOGGER.exception("Supervisor planning model call failed; using safe plan")
        selected = ["evidence", "safety"]
        for name in requested:
            if name in self.agent_names and name not in selected:
                selected.append(name)
        text = incident.narrative.lower()
        if any(marker in text for marker in UNCERTAIN_MARKERS) and "site_operations" not in selected:
            selected.append("site_operations")
        return selected[: len(self.agent_names)]

    def run(self, incident: IncidentRequest) -> RunState:
        if self.model is None:
            raise RuntimeError("A model client is required to run the graph")

        state = RunState(incident=incident)
        self.audit.record(
            state.run_id,
            "clinical_supervisor",
            "run_started",
            incident.model_dump(),
        )

        intake = self.tools.register_intake_case(
            source_report_id=incident.report_id,
            study_id=incident.study_id,
            site_id=incident.site_id,
            subject_id=incident.subject_id,
            event_term=self._infer_event_term(incident.narrative),
            seriousness_text="assessment pending",
            narrative=incident.narrative,
            received_at=incident.received_at,
        )
        state.case_id = intake["case_id"]
        state.intake_created = bool(intake["created"])
        self.audit.record(state.run_id, "intake", "case_registered", intake)

        state.selected_agents = self._select_agents(incident)
        self.audit.record(
            state.run_id,
            "clinical_supervisor",
            "plan_selected",
            {"agents": state.selected_agents},
        )

        for name in state.selected_agents:
            specialist = SpecialistAgent(name, self.model, self.tools, self.audit)
            state.specialist_results.append(specialist.run(state))

        evidence_package = [result.model_dump() for result in state.specialist_results]
        final_parse_failed = False
        try:
            final_message = self.model.complete(
                [
                    {
                        "role": "system",
                        "content": "Produce a JSON adverse-event assessment from all specialist results. Preserve conflicts and tool failures. Do not claim human review occurred. Include serious, uncertain, rationale, and site_follow_up fields.",
                    },
                    {"role": "user", "content": incident.model_dump_json()},
                    {"role": "user", "content": json.dumps(evidence_package, default=str)},
                ]
            )
            model_assessment = self._load_json(final_message.content)
            final_parse_failed = not bool(model_assessment)
        except Exception as exc:
            LOGGER.exception("Final disposition model call failed")
            model_assessment = {
                "uncertain": True,
                "rationale": "Final model call failed; no clinical conclusion was inferred.",
                "error_type": type(exc).__name__,
            }
            final_parse_failed = True

        tool_failures = [
            {
                "agent": result.agent_name,
                "tool": item["tool"],
                "error_type": item["outcome"].get("error_type"),
                "error": item["outcome"].get("error"),
            }
            for result in state.specialist_results
            for item in result.tool_activity
            if not item["outcome"].get("ok")
        ]
        combined = " ".join(
            [incident.narrative, json.dumps(model_assessment, default=str)]
            + [result.conclusion for result in state.specialist_results]
        ).lower()
        serious = bool(model_assessment.get("serious")) or any(
            marker in combined for marker in SERIOUS_MARKERS
        )
        uncertain = (
            final_parse_failed
            or bool(model_assessment.get("uncertain"))
            or bool(tool_failures)
            or any(result.bounded_stop for result in state.specialist_results)
            or any(marker in combined for marker in UNCERTAIN_MARKERS)
        )
        human_review_required = serious or uncertain
        review: dict[str, Any] | None = None
        review_completed = False
        if human_review_required:
            review = self.tools.ensure_physician_review(
                state.case_id,
                "Serious or uncertain adverse-event assessment requires physician review.",
            )
            review_completed = self.tools.physician_review_completed(state.case_id)

        follow_up: dict[str, Any] | None = None
        follow_up_reason = model_assessment.get("site_follow_up")
        if uncertain and not follow_up_reason:
            follow_up_reason = "Provide missing or conflicting source evidence for safety assessment."
        if follow_up_reason:
            follow_up = self.tools.create_site_follow_up(
                source_report_id=incident.report_id,
                study_id=incident.study_id,
                site_id=incident.site_id,
                subject_id=incident.subject_id,
                reason=str(follow_up_reason),
            )
            self.audit.record(state.run_id, "site_operations", "follow_up_registered", follow_up)

        status = (
            "completed"
            if not human_review_required or review_completed
            else "awaiting_physician_review"
        )
        evidence_quality = "degraded" if tool_failures or final_parse_failed else (
            "incomplete" if uncertain else "available"
        )
        state.final_result = {
            "case_id": state.case_id,
            "disposition_status": status,
            "serious": serious,
            "uncertain": uncertain,
            "human_review_required": human_review_required,
            "human_review_completed": review_completed,
            "physician_review": review,
            "evidence_quality": evidence_quality,
            "tool_failures": tool_failures,
            "site_follow_up": follow_up,
            "model_assessment": model_assessment,
            "specialist_evidence": evidence_package,
        }
        self.tools.save_disposition(
            state.case_id,
            state.run_id,
            status,
            human_review_required,
            evidence_quality,
            state.final_result,
        )
        state.finished_at = datetime.now(timezone.utc)
        self.audit.record(
            state.run_id,
            "clinical_supervisor",
            "run_finished",
            {
                "case_id": state.case_id,
                "status": status,
                "human_review_required": human_review_required,
                "human_review_completed": review_completed,
                "serious": serious,
                "uncertain": uncertain,
                "evidence_quality": evidence_quality,
                "tool_failures": tool_failures,
                "selected_agents": state.selected_agents,
            },
        )
        return state
