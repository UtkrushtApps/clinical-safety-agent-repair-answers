from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from agent.app import build_graph
from agent.config import Settings
from agent.selfcheck import run_selfcheck
from agent.state import IncidentRequest


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?")
    parser.add_argument("--selfcheck", action="store_true")
    arguments = parser.parse_args()

    if arguments.selfcheck:
        run_selfcheck()
        return
    if not arguments.fixture:
        parser.error("Provide a fixture path or use --selfcheck")

    payload = json.loads(Path(arguments.fixture).read_text())
    incident = IncidentRequest.model_validate(payload)
    graph = build_graph(Settings.from_env(), with_model=True)
    result = graph.run(incident)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
