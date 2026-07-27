"""Built-in example workflows and datasets (Orange-style starter templates)."""

from __future__ import annotations

import json
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.i18n import is_en, pick

EXAMPLES_DIR = Path(__file__).resolve().parent
DATASETS_DIR = EXAMPLES_DIR / "datasets"
WORKFLOWS_DIR = EXAMPLES_DIR / "workflows"


def list_examples(*, locale: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            {
                "id": meta.get("id") or path.stem,
                "title": pick(
                    locale,
                    meta.get("title") or path.stem,
                    meta.get("title_en") or meta.get("title") or path.stem,
                ),
                "description": pick(
                    locale,
                    meta.get("description") or "",
                    meta.get("description_en") or meta.get("description") or "",
                ),
                "dataset": meta.get("dataset"),
            }
        )
    return items


def _load_template(example_id: str) -> dict[str, Any]:
    path = WORKFLOWS_DIR / f"{example_id}.json"
    if not path.is_file():
        # allow stem match when id differs from filename
        for candidate in WORKFLOWS_DIR.glob("*.json"):
            meta = json.loads(candidate.read_text(encoding="utf-8"))
            if meta.get("id") == example_id:
                return meta
        raise FileNotFoundError(
            pick(None, f"未找到示例模板：{example_id}", f"Example template not found: {example_id}")
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _localize_graph(graph: dict[str, Any], locale: str | None) -> dict[str, Any]:
    """Swap node labels / intents to English overlays when present."""
    if not is_en(locale):
        return graph
    for node in graph.get("nodes", []):
        data = node.setdefault("data", {})
        if data.get("label_en"):
            data["label"] = data["label_en"]
        params = data.get("params") or {}
        if params.get("intent_en"):
            params["intent"] = params["intent_en"]
        if params.get("ai_intent_en"):
            params["ai_intent"] = params["ai_intent_en"]
        data["params"] = params
    for ann in graph.get("annotations", []):
        if ann.get("content_en"):
            ann["content"] = ann["content_en"]
    return graph


def instantiate_example(
    example_id: str,
    *,
    instance_path: str | Path,
    export_name: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    """Materialize a template: copy dataset into instance uploads, resolve paths."""
    meta = _load_template(example_id)
    graph = _localize_graph(deepcopy(meta["graph"]), locale)
    instance_path = Path(instance_path)
    uploads = instance_path / "uploads" / "examples"
    exports = instance_path / "exports"
    uploads.mkdir(parents=True, exist_ok=True)
    exports.mkdir(parents=True, exist_ok=True)

    def _copy_dataset(name: str) -> str:
        src = DATASETS_DIR / name
        if not src.is_file():
            raise FileNotFoundError(
                pick(
                    locale,
                    f"示例数据集不存在：{name}",
                    f"Example dataset missing: {name}",
                )
            )
        dest = uploads / f"{uuid.uuid4().hex}_{name}"
        shutil.copy2(src, dest)
        return str(dest)

    dataset_name = meta.get("dataset")
    dataset_path = _copy_dataset(dataset_name) if dataset_name else ""

    # Optional named extras, e.g. {"CUSTOMERS_PATH": "customers.csv"} → {{CUSTOMERS_PATH}}
    path_tokens: dict[str, str] = {"DATASET_PATH": dataset_path}
    extras = meta.get("extra_datasets") or {}
    if isinstance(extras, dict):
        for token, name in extras.items():
            if not isinstance(token, str) or not isinstance(name, str):
                continue
            path_tokens[token] = _copy_dataset(name)

    export_path = str(exports / (export_name or f"{example_id}.pdf"))
    path_tokens["EXPORT_PATH"] = export_path

    for node in graph.get("nodes", []):
        params = (node.get("data") or {}).get("params") or {}
        for key, value in list(params.items()):
            if isinstance(value, str):
                for token, resolved in path_tokens.items():
                    value = value.replace("{{" + token + "}}", resolved)
                params[key] = value
        node.setdefault("data", {})["params"] = params

    return {
        "id": meta.get("id") or example_id,
        "title": pick(
            locale,
            meta.get("title") or example_id,
            meta.get("title_en") or meta.get("title") or example_id,
        ),
        "description": pick(
            locale,
            meta.get("description") or "",
            meta.get("description_en") or meta.get("description") or "",
        ),
        "dataset_path": dataset_path,
        "export_path": export_path,
        "graph": graph,
    }
