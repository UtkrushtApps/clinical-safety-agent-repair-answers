from agent.app import build_graph
from agent.config import Settings
from agent.tool_schemas import TOOL_SCHEMAS


def test_package_and_graph_construct() -> None:
    settings = Settings.from_env()
    graph = build_graph(settings, with_model=False)
    assert graph is not None
    assert graph.describe()
    assert TOOL_SCHEMAS
