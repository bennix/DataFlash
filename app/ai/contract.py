"""AI output contract parsing (SPEC 4.3 + steps reserved)."""

from __future__ import annotations

import json
from typing import Any


class ModelContractError(ValueError):
    pass


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_model_payload(content: str | None) -> dict[str, Any]:
    text = _strip_fence(content or "")
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("模型响应中没有 JSON 对象", text, 0)
    payload, _end = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(payload, dict):
        raise ModelContractError("模型响应不是 JSON 对象")
    if not isinstance(payload.get("code"), str) or not payload.get("code", "").strip():
        fields = ", ".join(str(key) for key in payload.keys()) or "（无字段）"
        raise ModelContractError(f"模型 JSON 缺少非空字符串字段 code；实际字段：{fields}")
    code = payload["code"].strip()
    if code.startswith("```"):
        code = _strip_fence(code)
        # also handle ```python
        if code.startswith("python\n"):
            code = code[len("python\n") :]
        payload["code"] = code
    else:
        payload["code"] = code
    payload.setdefault("explanation", "")
    payload.setdefault("assumptions", [])
    payload.setdefault("steps", None)
    return payload
