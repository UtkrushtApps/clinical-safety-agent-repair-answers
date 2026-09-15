from __future__ import annotations

import json
from pathlib import Path

import psycopg

from agent.app import build_graph
from agent.config import Settings
from agent.model_client import ModelClient
from agent.state import IncidentRequest


def run_selfcheck() -> None:
    settings = Settings.from_env()
    fixture_directory = Path(__file__).resolve().parents[1] / "fixtures"
    fixture_paths = sorted(fixture_directory.glob("*.json"))
    if not fixture_paths:
        raise RuntimeError("No clinical fixtures were found")
    for path in fixture_paths:
        IncidentRequest.model_validate(json.loads(path.read_text()))

    graph = build_graph(settings, with_model=False)
    if not graph.describe():
        raise RuntimeError("Agent graph could not be constructed")

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM trial_subjects")
            if cursor.fetchone()[0] < 1:
                raise RuntimeError("Clinical seed data is unavailable")

    print("Fixtures, database, tools, and agent graph are ready")
    if settings.api_key:
        reply = ModelClient(settings).ping()
        print(f"Provider ping completed: {reply[:80]}")
    else:
        print("OPENAI_API_KEY is absent; provider ping skipped")
