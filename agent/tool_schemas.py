from __future__ import annotations

from typing import Any


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_protocol",
            "description": "Read protocol information for the current report's study.",
            "parameters": _object({"study_id": {"type": "string"}}, ["study_id"]),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subject_evidence",
            "description": "Read bounded visits, deviations, queries, and notes for the current subject.",
            "parameters": _object(
                {
                    "study_id": {"type": "string"},
                    "subject_id": {"type": "string"},
                    "site_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                ["study_id", "site_id", "subject_id"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_prior_events",
            "description": "Find prior safety reports for the current trial subject.",
            "parameters": _object(
                {
                    "study_id": {"type": "string"},
                    "subject_id": {"type": "string"},
                    "event_term": {"type": "string"},
                },
                ["study_id", "subject_id"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_site_follow_up",
            "description": "Idempotently create work requesting missing evidence from the current site.",
            "parameters": _object(
                {
                    "study_id": {"type": "string"},
                    "site_id": {"type": "string"},
                    "subject_id": {"type": "string"},
                    "source_report_id": {"type": "string"},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                },
                ["study_id", "site_id", "subject_id", "source_report_id", "reason"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_reporting_clock",
            "description": "Work out the regulatory reporting deadline for a report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "study_id": {"type": "string"},
                    "received_at": {"type": "string"},
                    "seriousness_text": {"type": "string"},
                },
                "required": ["study_id", "received_at"],
                "additionalProperties": False,
            },
        },
    },    {
        "type": "function",
        "function": {
            "name": "classify_seriousness",
            "description": "Assess the seriousness of a reported event for the study.",
            "parameters": _object(
                {
                    "study_id": {"type": "string"},
                    "narrative": {"type": "string"},
                    "subject_id": {"type": "string"},
                },
                ["study_id", "narrative"],
            ),
        },
    },
]


def schemas_for_agent(agent_name: str) -> list[dict[str, Any]]:
    if agent_name == "site_operations":
        return [TOOL_SCHEMAS[1], TOOL_SCHEMAS[3]]
    if agent_name == "safety":
        return TOOL_SCHEMAS[:3] + [TOOL_SCHEMAS[4], TOOL_SCHEMAS[5]]
    return TOOL_SCHEMAS[:3]
