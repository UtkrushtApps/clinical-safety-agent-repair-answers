from __future__ import annotations

from agent.audit import AuditWriter
from agent.config import Settings
from agent.model_client import ModelClient
from agent.orchestrator import ClinicalAgentGraph
from agent.tools import ClinicalTools


def build_graph(settings: Settings, with_model: bool = True) -> ClinicalAgentGraph:
    tools = ClinicalTools(
        settings.database_url,
        timeout_ms=settings.tool_timeout_ms,
        evidence_lookup_delay_ms=settings.evidence_lookup_delay_ms,
    )
    audit = AuditWriter(settings.database_url)
    model = ModelClient(settings) if with_model else None
    return ClinicalAgentGraph(model=model, tools=tools, audit=audit)
