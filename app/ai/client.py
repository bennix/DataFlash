"""ZenMux OpenAI-compatible client with retry (SPEC 4.1)."""

from __future__ import annotations

import json
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from app.schema import TableSchema, infer_schema

from app.i18n import is_en, pick

from .prompts import system_prompt, user_prompt
from .contract import ModelContractError, parse_model_payload

BASE_URL = "https://zenmux.ai/api/v1"
DEFAULT_MODELS = [
    "anthropic/claude-sonnet-4.6",
    "z-ai/glm-5v-turbo",
    "openai/gpt-5.4",
    "anthropic/claude-opus-5",
    "moonshotai/kimi-k3",
]


def summarize_dataframe(df, *, mask_samples: bool = True) -> dict[str, Any]:
    schema = infer_schema(df, mask_samples=mask_samples)
    return schema.for_ai()


def _friendly_ai_error(exc: Exception, locale: str | None) -> str:
    """User-facing message for common ZenMux / OpenAI transport failures."""
    if isinstance(exc, AuthenticationError):
        return pick(
            locale,
            "AI 服务鉴权失败：请检查设置中的 ZenMux API Key 是否有效。",
            "AI auth failed: check that your ZenMux API key in Settings is valid.",
        )
    if isinstance(exc, RateLimitError):
        return pick(
            locale,
            "AI 服务请求过于频繁，请稍后重试。",
            "AI rate limit hit; please retry shortly.",
        )
    if isinstance(exc, APITimeoutError):
        return pick(
            locale,
            "AI 服务响应超时。请稍后重试，或换一个更快的模型。",
            "AI request timed out. Retry later, or switch to a faster model.",
        )
    if isinstance(exc, APIConnectionError):
        return pick(
            locale,
            "无法连接 AI 服务（ZenMux）。请检查网络后重试；若持续失败，可稍后再跑或改用其他模型。",
            "Cannot reach the AI service (ZenMux). Check your network and retry; "
            "if it persists, wait a bit or try another model.",
        )
    if isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", None)
        detail = getattr(exc, "message", None) or str(exc)
        return pick(
            locale,
            f"AI 服务返回错误（HTTP {status}）：{detail}",
            f"AI service error (HTTP {status}): {detail}",
        )
    return str(exc) or pick(locale, "AI 调用失败", "AI call failed")


def generate(
    api_key: str,
    model: str,
    node_type: str,
    intent: str,
    summary: dict | list | TableSchema,
    *,
    retries: int = 2,
    heal_traceback: str | None = None,
    heal_code: str | None = None,
    locale: str | None = None,
) -> tuple[dict, Any]:
    client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=90, max_retries=0)
    if isinstance(summary, TableSchema):
        summary_payload = summary.for_ai()
    elif isinstance(summary, list):
        summary_payload = {"schema": summary, "row_count": None}
    else:
        summary_payload = summary

    message = user_prompt(
        node_type,
        intent,
        summary_payload,
        heal_traceback,
        heal_code,
        locale=locale,
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt(locale)},
                    {"role": "user", "content": message},
                ],
                response_format={"type": "json_object"},
            )
            return parse_model_payload(response.choices[0].message.content), response.usage
        except Exception as e:
            last = e
            if isinstance(e, (json.JSONDecodeError, ModelContractError)) and attempt < retries:
                if is_en(locale):
                    message += (
                        f"\n\nPrevious response violated the output contract: {e}. "
                        "Fix it and return only a JSON object with non-empty code, explanation, assumptions. "
                        "Assign table/stats to result (figures to fig)."
                    )
                else:
                    message += (
                        f"\n\n上一次响应违反输出契约：{e}。"
                        "请修正并只返回包含非空 code、explanation、assumptions 的 JSON 对象。"
                        "code 必须把结果赋给 result（图表赋给 fig）。"
                    )
                continue
            status = getattr(e, "status_code", None)
            retryable = isinstance(
                e, (RateLimitError, APIConnectionError, APITimeoutError)
            ) or (
                isinstance(e, APIStatusError) and status is not None and status >= 500
            )
            if attempt >= retries or not retryable:
                if isinstance(
                    e,
                    (
                        APIConnectionError,
                        APITimeoutError,
                        AuthenticationError,
                        RateLimitError,
                        APIStatusError,
                    ),
                ):
                    raise RuntimeError(_friendly_ai_error(e, locale)) from e
                raise
            time.sleep(2**attempt)
    assert last is not None
    if isinstance(
        last,
        (
            APIConnectionError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
            APIStatusError,
        ),
    ):
        raise RuntimeError(_friendly_ai_error(last, locale)) from last
    raise last


def mock_generate(node_type: str, params: dict, df, locale: str | None = None) -> dict:
    """Deterministic mock for offline E2E (D1–D5)."""
    from app.i18n import pick

    intent = params.get("intent") or params.get("ai_intent") or ""
    if params.get("_heal_traceback"):
        # Simple heal: return a safe passthrough
        return {
            "code": "result = df.dropna().drop_duplicates() if hasattr(df, 'dropna') else df",
            "explanation": pick(
                locale, "自愈：安全降级为去重去空", "Heal: safe fallback dropna/dedupe"
            ),
            "assumptions": ["heal fallback"],
            "steps": None,
        }
    if node_type == "ai_clean":
        return {
            "code": "result = df.dropna().drop_duplicates()",
            "explanation": pick(locale, "删除空值并去重", "Drop nulls and duplicates"),
            "assumptions": [],
            "steps": None,
        }
    if node_type == "filter":
        expr = params.get("expression")
        if expr:
            return {
                "code": f"result = df.query({expr!r}, engine='python')",
                "explanation": pick(
                    locale, f"按表达式筛选：{expr}", f"Filter by expression: {expr}"
                ),
                "assumptions": [],
                "steps": None,
            }
        return {
            "code": "result = df",
            "explanation": pick(locale, "无筛选条件，透传", "No filter; passthrough"),
            "assumptions": [],
            "steps": None,
        }
    if node_type == "ai_analyze":
        return {
            "code": (
                "result = {\n"
                "  'row_count': int(len(df)),\n"
                "  'columns': [str(c) for c in df.columns],\n"
                "  'describe': df.describe(include='all').fillna('').to_dict(),\n"
                "  'intent': " + repr(intent) + ",\n"
                "}\n"
            ),
            "explanation": pick(locale, "描述统计", "Descriptive statistics"),
            "assumptions": [],
            "steps": None,
        }
    if node_type == "ai_chart":
        x = params.get("x") or (str(df.columns[0]) if df is not None and len(df.columns) else "x")
        y = params.get("y") or (
            str(df.columns[1]) if df is not None and len(df.columns) > 1 else x
        )
        color = params.get("color")
        color_arg = f", color={color!r}" if color else ""
        return {
            "code": f"fig = px.scatter(df, x={x!r}, y={y!r}{color_arg}, title='AI Chart')",
            "explanation": pick(locale, f"散点图 {x} vs {y}", f"Scatter {x} vs {y}"),
            "assumptions": [],
            "steps": None,
        }
    if node_type == "ai_report":
        if is_en(locale):
            code = (
                "result = '# Data analysis report\\n\\n'\n"
                f"result += 'Intent: {intent}\\n\\n'\n"
                "result += f'Rows: {len(df)}\\n\\n'\n"
                "result += '## Columns\\n' + ', '.join(str(c) for c in df.columns)\n"
            )
        else:
            code = (
                "result = '# 数据分析报告\\n\\n'\n"
                f"result += '意图：{intent}\\n\\n'\n"
                "result += f'行数：{len(df)}\\n\\n'\n"
                "result += '## 列\\n' + ', '.join(str(c) for c in df.columns)\n"
            )
        return {
            "code": code,
            "explanation": pick(locale, "生成 Markdown 报告", "Generate Markdown report"),
            "assumptions": [],
            "steps": None,
        }
    if node_type == "custom.ai_flag_rows" or (
        isinstance(node_type, str) and node_type.startswith("custom.") and "flag" in node_type
    ):
        # Deterministic demo: Flag = Fare > 50 when Fare exists, else False
        code = (
            "out = df.copy()\n"
            "if 'Fare' in out.columns:\n"
            "    out['Flag'] = out['Fare'].fillna(0) > 50\n"
            "else:\n"
            "    out['Flag'] = False\n"
            "result = out\n"
        )
        return {
            "code": code,
            "explanation": pick(
                locale,
                "Mock：Fare>50 标记为 Flag",
                "Mock: set Flag where Fare>50",
            ),
            "assumptions": ["mock threshold Fare>50"],
            "steps": None,
        }
    if isinstance(node_type, str) and node_type.startswith("custom."):
        # Generic custom AI table node: passthrough with note column
        return {
            "code": (
                "out = df.copy()\n"
                "out['AI_Note'] = " + repr(str(intent)[:80]) + "\n"
                "result = out\n"
            ),
            "explanation": pick(locale, "自定义 AI 节点 mock 透传", "Custom AI mock passthrough"),
            "assumptions": [],
            "steps": None,
        }
    return {
        "code": "result = df",
        "explanation": pick(locale, "透传", "Passthrough"),
        "assumptions": [],
        "steps": None,
    }
