from __future__ import annotations

import json
import logging
from typing import Any

from agent.audit import AuditWriter
from agent.model_client import ModelClient
from agent.state import RunState, SpecialistResult
from agent.tool_schemas import schemas_for_agent
from agent.tools import ClinicalTools

LOGGER = logging.getLogger(__name__)

ROLE_PROMPTS = {
    "evidence": "Review the available PostgreSQL clinical evidence. Distinguish facts, missing records, and conflicts. Never convert a tool failure into a clinical fact. Return a concise JSON conclusion.",
    "safety": "Review seriousness and uncertainty conservatively. Missing or conflicting evidence must remain explicit and may require physician review. Never claim a failed tool succeeded. Return concise JSON.",
    "site_operations": "Review missing site information and use at most one idempotent follow-up when justified. Never repeatedly call a tool to obtain unavailable details. Return concise JSON.",
}


class SpecialistAgent:
    MAX_TOOL_ROUNDS = 2
    MAX_TOOL_EXECUTIONS = 6

    def __init__(
        self,
        name: str,
        model: ModelClient,
        tools: ClinicalTools,
        audit: AuditWriter,
    ) -> None:
        self.name = name
        self.model = model
        self.tools = tools
        self.audit = audit

    @staticmethod
    def _message_dict(message: Any) -> dict[str, Any]:
        if hasattr(message, "model_dump"):
            return message.model_dump(exclude_none=True)
        if isinstance(message, dict):
            return message
        return {"role": "assistant", "content": getattr(message, "content", None)}

    def run(self, state: RunState) -> SpecialistResult:
        schemas = schemas_for_agent(self.name)
        allowed = {schema["function"]["name"] for schema in schemas}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ROLE_PROMPTS[self.name]},
            {"role": "user", "content": state.incident.model_dump_json()},
        ]
        activity: list[dict[str, Any]] = []
        seen_calls: set[str] = set()
        model_calls = 0
        bounded_stop = False
        context = {
            "study_id": state.incident.study_id,
            "site_id": state.incident.site_id,
            "subject_id": state.incident.subject_id,
            "source_report_id": state.incident.report_id,
        }

        try:
            response = self.model.complete(messages, tools=schemas)
            model_calls += 1
            for _round in range(self.MAX_TOOL_ROUNDS):
                tool_calls = list(getattr(response, "tool_calls", None) or [])
                if not tool_calls:
                    break
                messages.append(self._message_dict(response))
                for call in tool_calls:
                    name = call.function.name
                    raw_arguments = call.function.arguments or "{}"
                    signature = f"{name}:{raw_arguments}"
                    if signature in seen_calls:
                        outcome = {
                            "ok": False,
                            "error_type": "DuplicateToolCall",
                            "error": "identical tool call was already attempted",
                        }
                    elif len(activity) >= self.MAX_TOOL_EXECUTIONS:
                        outcome = {
                            "ok": False,
                            "error_type": "ToolBudgetExceeded",
                            "error": "specialist tool execution budget exhausted",
                        }
                    else:
                        seen_calls.add(signature)
                        outcome = self.tools.dispatch(
                            name,
                            raw_arguments,
                            context=context,
                            allowed_tools=allowed,
                        )
                    try:
                        safe_arguments: Any = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        safe_arguments = {"invalid_json": True}
                    entry = {"tool": name, "arguments": safe_arguments, "outcome": outcome}
                    activity.append(entry)
                    self.audit.record(state.run_id, self.name, "tool_call", entry)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(outcome, default=str),
                        }
                    )
                response = self.model.complete(messages, tools=schemas)
                model_calls += 1
            if getattr(response, "tool_calls", None):
                bounded_stop = True
                conclusion = json.dumps(
                    {
                        "status": "incomplete",
                        "reason": "bounded tool/model budget exhausted",
                        "uncertain": True,
                    }
                )
            else:
                conclusion = response.content or json.dumps(
                    {"status": "incomplete", "reason": "no conclusion", "uncertain": True}
                )
        except Exception as exc:
            LOGGER.exception("Specialist %s failed", self.name)
            conclusion = json.dumps(
                {
                    "status": "incomplete",
                    "reason": "model provider failure",
                    "error_type": type(exc).__name__,
                    "uncertain": True,
                }
            )
            bounded_stop = True

        result = SpecialistResult(
            agent_name=self.name,
            conclusion=conclusion,
            tool_activity=activity,
            model_calls=model_calls,
            bounded_stop=bounded_stop,
        )
        self.audit.record(
            state.run_id,
            self.name,
            "specialist_result",
            result.model_dump(),
        )
        return result
