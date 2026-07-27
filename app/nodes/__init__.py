"""Import all node modules so they self-register."""

from app.nodes import (  # noqa: F401
    ai_analyze,
    ai_chart,
    ai_clean,
    ai_report,
    export_node,
    file_input,
    filter_node,
    groupby_node,
    join_node,
    preview,
)
from app.registry import all_specs, get_spec

# Backward-compatible names used by older api/tests
NODES = all_specs()
REGISTRY = {s.type: s for s in all_specs()}


def refresh() -> None:
    global NODES, REGISTRY
    NODES = all_specs()
    REGISTRY = {s.type: s for s in all_specs()}


__all__ = ["NODES", "REGISTRY", "all_specs", "get_spec", "refresh"]
