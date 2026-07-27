"""Compatibility shim — prefer ``app.sandbox.validator``."""

from __future__ import annotations

from .sandbox.validator import CodeRejected, ensure_safe, validate


class UnsafeCode(ValueError):
    pass


def validate_code(code: str):
    result = validate(code)
    if not result.ok:
        raise UnsafeCode(result.summary or "代码未通过安全校验")
    return True
