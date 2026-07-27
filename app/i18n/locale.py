from __future__ import annotations

from typing import Any

DEFAULT_LOCALE = "zh-CN"
SUPPORTED = frozenset({"zh-CN", "zh", "en", "en-US", "en-GB"})


def normalize_locale(value: str | None) -> str:
    if not value:
        return DEFAULT_LOCALE
    text = str(value).strip().replace("_", "-")
    if not text:
        return DEFAULT_LOCALE
    lower = text.lower()
    if lower.startswith("en"):
        return "en"
    if lower.startswith("zh"):
        return "zh-CN"
    return DEFAULT_LOCALE


def is_en(locale: str | None) -> bool:
    return normalize_locale(locale) == "en"


def pick(locale: str | None, zh: Any, en: Any) -> Any:
    """Pick zh/en value; fall back to the other if empty."""
    if is_en(locale):
        return en if en not in (None, "") else zh
    return zh if zh not in (None, "") else en


def resolve_request_locale(
    *,
    explicit: str | None = None,
    accept_language: str | None = None,
    stored: str | None = None,
) -> str:
    if explicit:
        return normalize_locale(explicit)
    if stored:
        return normalize_locale(stored)
    if accept_language:
        # Take first tag: "en-US,en;q=0.9,zh-CN;q=0.8"
        primary = accept_language.split(",")[0].split(";")[0].strip()
        return normalize_locale(primary)
    return DEFAULT_LOCALE
