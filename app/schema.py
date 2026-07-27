"""Typed table schema: Column / TableSchema, inference, PII masking.

Borrowed from Orange Domain/Variable (kind + role), adapted for pandas.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

Kind = Literal["numeric", "categorical", "datetime", "text", "boolean"]
Role = Literal["feature", "target", "meta", "skip"]

# Orange-inspired thresholds (variable.py DISCRETE_MAX_*)
DISCRETE_MAX_VALUES = 3
DISCRETE_MAX_ALLOWED_VALUES = 100
DISCRETE_POWER = 0.7
DATETIME_PARSE_RATIO = 0.95
SAMPLE_LIMIT = 3
SAMPLE_MAX_CHARS = 32

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("phone", re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")),
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("long_digits", re.compile(r"(?<!\d)\d{11,}(?!\d)")),
]


@dataclass(frozen=True)
class Column:
    name: str
    kind: Kind
    dtype: str
    role: Role = "feature"
    null_pct: float = 0.0
    n_unique: int = 0
    categories: tuple[str, ...] | None = None
    stats: dict[str, Any] | None = None
    samples: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def for_ai(self) -> dict[str, Any]:
        """Schema-only payload for the model (SPEC 4.2)."""
        item: dict[str, Any] = {
            "col": self.name,
            "dtype": self.dtype,
            "kind": self.kind,
            "role": self.role,
            "null_pct": self.null_pct,
            "n_unique": self.n_unique,
        }
        if self.kind in ("numeric", "boolean") and self.stats:
            item.update({k: self.stats[k] for k in ("min", "max", "mean") if k in self.stats})
        else:
            item["samples"] = list(self.samples)
        if self.categories is not None and len(self.categories) <= 20:
            item["categories"] = list(self.categories)
        return item


@dataclass(frozen=True)
class TableSchema:
    columns: tuple[Column, ...]
    row_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": [c.to_dict() for c in self.columns],
            "row_count": self.row_count,
        }

    def for_ai(self) -> dict[str, Any]:
        return {
            "schema": [c.for_ai() for c in self.columns],
            "row_count": self.row_count,
        }

    def fingerprint(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def column_names(self) -> set[str]:
        return {c.name for c in self.columns}

    def get(self, name: str) -> Column | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def public_columns(self) -> list[dict[str, Any]]:
        """Compact column list for inspector / SSE (name + type)."""
        return [
            {
                "name": c.name,
                "kind": c.kind,
                "dtype": c.dtype,
                "role": c.role,
                "null_pct": c.null_pct,
                "n_unique": c.n_unique,
            }
            for c in self.columns
        ]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableSchema:
        cols = tuple(Column(**{**c, "categories": tuple(c["categories"]) if c.get("categories") else None,
                               "samples": tuple(c.get("samples") or ())}) for c in data["columns"])
        return cls(columns=cols, row_count=int(data["row_count"]))


def schema_public(schema: TableSchema | None) -> dict[str, Any] | None:
    if schema is None:
        return None
    return {
        "row_count": schema.row_count,
        "columns": schema.public_columns(),
        "for_ai": schema.for_ai(),
    }


def mask_pii(value: str, *, enabled: bool = True) -> str:
    text = str(value)[:SAMPLE_MAX_CHARS]
    if not enabled:
        return text
    for label, pattern in _PII_PATTERNS:
        text = pattern.sub(f"<masked:{label}>", text)
    return text


def _is_boolean_like(series: pd.Series, n_unique: int) -> bool:
    if n_unique == 0 or n_unique > DISCRETE_MAX_VALUES:
        return False
    vals = set(series.dropna().unique().tolist())
    # Normalize to comparable forms
    normalized: set[Any] = set()
    for v in vals:
        if isinstance(v, (bool, np.bool_)):
            normalized.add(bool(v))
        elif isinstance(v, (int, np.integer)) or (isinstance(v, float) and v.is_integer()):
            normalized.add(int(v))
        elif isinstance(v, str) and v.lower() in {"true", "false", "0", "1", "yes", "no"}:
            normalized.add(v.lower())
        else:
            return False
    return normalized.issubset({0, 1, True, False, "true", "false", "0", "1", "yes", "no"})


def _is_categorical(series: pd.Series, n_unique: int, n: int) -> bool:
    if n_unique == 0 or n_unique > DISCRETE_MAX_ALLOWED_VALUES:
        return False
    if pd.api.types.is_numeric_dtype(series):
        return n_unique <= DISCRETE_MAX_VALUES and _is_boolean_like(series, n_unique) is False \
            and set(series.dropna().unique().tolist()).issubset({0, 1, 1.0, 0.0, 2, 2.0})
    # Non-numeric: Orange n**0.7 rule
    return n_unique <= max(2, round(n ** DISCRETE_POWER))


def _try_datetime(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_numeric_dtype(series):
        return False
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return False
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return float(parsed.notna().mean()) >= DATETIME_PARSE_RATIO


def infer_kind(series: pd.Series) -> Kind:
    n = len(series)
    n_unique = int(series.nunique(dropna=True))
    if pd.api.types.is_bool_dtype(series) or _is_boolean_like(series, n_unique):
        return "boolean"
    if _try_datetime(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        if _is_categorical(series, n_unique, n):
            return "categorical"
        return "numeric"
    if _is_categorical(series, n_unique, n):
        return "categorical"
    return "text"


def infer_schema(
    df: pd.DataFrame,
    *,
    roles: dict[str, Role] | None = None,
    mask_samples: bool = True,
) -> TableSchema:
    roles = roles or {}
    columns: list[Column] = []
    for name in df.columns:
        series = df[name]
        kind = infer_kind(series)
        n_unique = int(series.nunique(dropna=True))
        null_pct = float(series.isna().mean()) if len(series) else 0.0
        categories: tuple[str, ...] | None = None
        stats: dict[str, Any] | None = None
        samples: tuple[str, ...] = ()

        if kind == "categorical":
            cats = series.dropna().astype(str).value_counts().head(50).index.tolist()
            categories = tuple(cats)
            samples = tuple(mask_pii(v, enabled=mask_samples) for v in cats[:SAMPLE_LIMIT])
        elif kind in ("numeric", "boolean"):
            values = pd.to_numeric(series, errors="coerce").dropna()
            if len(values):
                stats = {
                    "min": float(values.min()),
                    "max": float(values.max()),
                    "mean": float(values.mean()),
                    "std": float(values.std()) if len(values) > 1 else 0.0,
                }
        elif kind == "datetime":
            dt = pd.to_datetime(series, errors="coerce", format="mixed")
            valid = dt.dropna()
            if len(valid):
                stats = {"min": str(valid.min()), "max": str(valid.max())}
            samples = tuple(
                mask_pii(v, enabled=mask_samples)
                for v in series.dropna().astype(str).drop_duplicates().head(SAMPLE_LIMIT)
            )
        else:
            samples = tuple(
                mask_pii(v, enabled=mask_samples)
                for v in series.dropna().astype(str).drop_duplicates().head(SAMPLE_LIMIT)
            )

        columns.append(
            Column(
                name=str(name),
                kind=kind,
                dtype=str(series.dtype),
                role=roles.get(str(name), "feature"),
                null_pct=round(null_pct, 4),
                n_unique=n_unique,
                categories=categories,
                stats=stats,
                samples=samples,
            )
        )
    return TableSchema(columns=tuple(columns), row_count=int(len(df)))


def schema_summary_brief(schema: TableSchema) -> str:
    return f"{schema.row_count} × {len(schema.columns)}"


def schema_summary_detail(schema: TableSchema) -> str:
    counts: dict[str, int] = {}
    for col in schema.columns:
        counts[col.kind] = counts.get(col.kind, 0) + 1
    parts = [f"{n} {k}" for k, n in counts.items()]
    return f"{schema.row_count} 行，{len(schema.columns)} 列：{', '.join(parts) if parts else '空'}"
