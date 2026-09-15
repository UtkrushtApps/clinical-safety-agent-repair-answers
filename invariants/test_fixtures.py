import json
from pathlib import Path

from agent.state import IncidentRequest


def test_fixtures_parse() -> None:
    paths = list((Path(__file__).resolve().parents[1] / "fixtures").glob("*.json"))
    assert paths
    for path in paths:
        payload = json.loads(path.read_text())
        incident = IncidentRequest.model_validate(payload)
        assert incident is not None
