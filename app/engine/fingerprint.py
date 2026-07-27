"""Node fingerprint for incremental cache (SPEC 3.1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def fingerprint(
    node: dict[str, Any],
    upstream: list[str],
    code: str = "",
    file_stamp: str = "",
    schema_fp: str = "",
) -> str:
    data = node.get("data") or {}
    params = data.get("params") or node.get("params") or {}
    blob = (
        (node.get("type") or "")
        + canonical(params)
        + (code or data.get("code") or "")
        + "".join(upstream)
        + file_stamp
        + schema_fp
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def file_stamp(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    st = p.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"
