"""DAG topology sort (Kahn) and cycle detection."""

from __future__ import annotations

from typing import Any


def graph_order(
    graph: dict[str, Any], target: str | None = None
) -> tuple[list[str], dict[str, dict], list[dict]]:
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = list(graph.get("edges", []))

    if target:
        needed = {target}
        changed = True
        while changed:
            changed = False
            for e in edges:
                if e["target"] in needed and e["source"] not in needed:
                    needed.add(e["source"])
                    changed = True
        nodes = {k: v for k, v in nodes.items() if k in needed}
        edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]

    indeg = {k: 0 for k in nodes}
    nexts: dict[str, list[str]] = {k: [] for k in nodes}
    for e in edges:
        if e["target"] not in indeg or e["source"] not in indeg:
            continue
        indeg[e["target"]] += 1
        nexts[e["source"]].append(e["target"])

    queue = [k for k, v in indeg.items() if v == 0]
    out: list[str] = []
    while queue:
        key = queue.pop(0)
        out.append(key)
        for child in nexts[key]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)

    if len(out) != len(nodes):
        # Collect nodes involved in a cycle
        remaining = [k for k, v in indeg.items() if v > 0]
        raise CycleError(remaining)

    return out, nodes, edges


def layered_order(order: list[str], edges: list[dict]) -> list[list[str]]:
    """Group nodes into concurrent layers (no mutual dependencies)."""
    preds: dict[str, set[str]] = {n: set() for n in order}
    for e in edges:
        if e["target"] in preds and e["source"] in preds:
            preds[e["target"]].add(e["source"])
    done: set[str] = set()
    layers: list[list[str]] = []
    remaining = list(order)
    while remaining:
        layer = [n for n in remaining if preds[n].issubset(done)]
        if not layer:
            # Should not happen after cycle check; fall back to serial
            layer = [remaining[0]]
        layers.append(layer)
        for n in layer:
            done.add(n)
            remaining.remove(n)
    return layers


class CycleError(ValueError):
    def __init__(self, node_ids: list[str]):
        super().__init__("工作流包含环")
        self.node_ids = node_ids
