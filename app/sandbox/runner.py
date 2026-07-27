"""Spawn-based sandboxed code execution (SPEC 3.3 / 5.3 + delta §2.7–2.8).

Parent process only exchanges file paths and status — never DataFrames over IPC.
"""

from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import os
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .validator import CodeRejected, ensure_safe, strip_injected_imports, validate

# Extra forbidden attributes for AI/user code (code_profile="ai").
AI_EXTRA_FORBIDDEN_ATTRS: frozenset[str] = frozenset(
    {
        "read_csv",
        "read_excel",
        "read_json",
        "read_parquet",
        "read_feather",
        "read_orc",
        "read_fwf",
        "read_table",
        "read_html",
        "read_xml",
        "read_clipboard",
        "read_hdf",
        "to_csv",
        "to_excel",
        "to_json",
        "to_parquet",
        "to_feather",
        "to_orc",
        "to_html",
        "to_xml",
        "to_hdf",
        "to_sql",
        "to_clipboard",
        "to_latex",
        "to_markdown",
        "to_string",
        "to_dict",  # still allow? Actually to_dict is fine in-memory
    }
)

# Keep in-memory helpers; remove file IO ones for AI profile.
AI_FORBIDDEN_ATTRS_EFFECTIVE = AI_EXTRA_FORBIDDEN_ATTRS - {
    "to_dict",
    "to_string",
    "to_markdown",
    "to_latex",
}

def _sandbox_import(
    name: str,
    globals: Any = None,
    locals: Any = None,
    fromlist: Any = (),
    level: int = 0,
) -> Any:
    """Provide ``__import__`` for library internals / import opcodes.

    User code still cannot call ``__import__`` or write ``import`` — the AST
    validator rejects both. Without this entry, some paths raise
    ``KeyError: '__import__'`` / ``ImportError: __import__ not found``.
    """
    import builtins

    return builtins.__import__(name, globals, locals, fromlist, level)


SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "print": print,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "True": True,
    "False": False,
    "None": None,
    # Required by CPython import machinery & some library lazy-loads.
    # Not callable from user AST (dunder name + FORBIDDEN_CALLS).
    "__import__": _sandbox_import,
}


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    traceback: str = ""
    duration_ms: int = 0


def validate_for_profile(code: str, profile: str = "ai") -> str:
    """Validate code; AI profile strips redundant injected imports and bans IO helpers.

    Returns the (possibly rewritten) code that should be executed.
    """
    if profile == "ai":
        code = strip_injected_imports(code)
    ensure_safe(code)
    if profile != "ai":
        return code
    # Second pass: reject IO attributes via the same AST walk as validator
    import ast

    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in AI_FORBIDDEN_ATTRS_EFFECTIVE:
            raise RuntimeError(f"检测到危险属性 .{node.attr} 的使用（AI 档禁止文件 IO），已拦截")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in AI_FORBIDDEN_ATTRS_EFFECTIVE:
                raise RuntimeError(f"检测到 {node.func.attr}(...) 调用（AI 档禁止文件 IO），已拦截")
    return code


def _disable_network() -> None:
    import socket

    def _blocked(*_a, **_k):
        raise OSError("沙箱内网络访问已被禁用")

    socket.socket = _blocked  # type: ignore[assignment,method-assign]
    socket.create_connection = _blocked  # type: ignore[assignment]


def _apply_resource_limits(cpu_seconds: int = 30, as_bytes: int = 2 * 1024**3) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
        except (ValueError, OSError):
            pass  # macOS often ignores RLIMIT_AS; RSS watchdog in parent covers this
    except ImportError:
        pass


def _worker(
    input_paths: dict[str, str],
    output_path: str,
    code: str,
    result_var: str,
    result_kind: str,
    conn: Any,
) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        _apply_resource_limits()
        _disable_network()
        workdir = str(Path(output_path).parent)
        os.chdir(workdir)

        import collections
        import copy
        import datetime
        import decimal
        import functools
        import itertools
        import json
        import math
        import operator
        import re
        import statistics

        import numpy as np
        import pandas as pd
        import plotly
        import plotly.express as px
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        namespace: dict[str, Any] = {
            "__builtins__": SAFE_BUILTINS,
            "pd": pd,
            "np": np,
            "plotly": plotly,
            "px": px,
            "go": go,
            "make_subplots": make_subplots,
            # Common stdlib the model tries to import — preloaded + stripped.
            "json": json,
            "math": math,
            "statistics": statistics,
            "collections": collections,
            "re": re,
            "datetime": datetime,
            "decimal": decimal,
            "functools": functools,
            "itertools": itertools,
            "operator": operator,
            "copy": copy,
            "Counter": collections.Counter,
        }
        # Inject dataframes by port name; also expose single input as `df`
        frames = []
        for key, path in input_paths.items():
            frame = pd.read_parquet(path)
            namespace[key] = frame
            frames.append(frame)
        if len(frames) == 1:
            namespace["df"] = frames[0]
        elif len(frames) > 1:
            for i, frame in enumerate(frames, start=1):
                namespace[f"df{i}"] = frame
            namespace["df"] = frames[0]

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(code, "<dataflash>", "exec"), namespace, namespace)

        result = namespace.get(result_var)
        if result_kind == "table":
            if not isinstance(result, pd.DataFrame):
                raise ValueError(f"代码必须将 DataFrame 赋给 {result_var}")
            result.to_parquet(output_path)
        elif result_kind == "figure":
            from app.figures import figure_to_json

            if hasattr(result, "to_plotly_json") or isinstance(result, dict):
                Path(output_path).write_text(figure_to_json(result), encoding="utf-8")
            else:
                raise ValueError(f"代码必须将 plotly figure 赋给 {result_var}")
        else:
            import json

            Path(output_path).write_text(
                json.dumps(result, default=str, ensure_ascii=False), encoding="utf-8"
            )

        conn.send({"ok": True, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()})
    except Exception as exc:
        conn.send(
            {
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            }
        )
    finally:
        conn.close()


def run_sandboxed(
    *,
    code: str,
    input_paths: dict[str, str] | None = None,
    output_path: str | Path,
    result_var: str = "result",
    result_kind: str = "table",
    profile: str = "ai",
    timeout: float = 35.0,
    rss_limit_mb: int = 2048,
) -> SandboxResult:
    """Execute ``code`` in a spawn child. Returns status only."""
    try:
        code = validate_for_profile(code, profile)
    except CodeRejected as exc:
        return SandboxResult(ok=False, error=str(exc), traceback=str(exc))
    except RuntimeError as exc:
        # AI-profile IO attribute bans
        return SandboxResult(ok=False, error=str(exc), traceback=str(exc))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_paths = {k: str(v) for k, v in (input_paths or {}).items()}

    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    started = time.monotonic()
    process = ctx.Process(
        target=_worker,
        args=(input_paths, str(output_path), code, result_var, result_kind, child),
        daemon=True,
    )
    process.start()

    # RSS watchdog (macOS RLIMIT_AS is unreliable)
    deadline = started + timeout
    while process.is_alive() and time.monotonic() < deadline:
        try:
            import psutil  # optional

            rss = psutil.Process(process.pid).memory_info().rss / (1024 * 1024)
            if rss > rss_limit_mb:
                process.kill()
                process.join(5)
                return SandboxResult(
                    ok=False,
                    error=f"沙箱内存超过 {rss_limit_mb}MB 限制",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
        except Exception:
            pass
        process.join(0.2)

    if process.is_alive():
        process.kill()
        process.join(5)
        return SandboxResult(
            ok=False,
            error="沙箱执行超过 30 秒限制",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    payload = parent.recv() if parent.poll(1) else {"ok": False, "error": "沙箱进程异常退出"}
    duration_ms = int((time.monotonic() - started) * 1000)
    if not payload.get("ok"):
        return SandboxResult(
            ok=False,
            error=payload.get("error", "沙箱执行失败"),
            traceback=payload.get("traceback", ""),
            stdout=payload.get("stdout", ""),
            stderr=payload.get("stderr", ""),
            duration_ms=duration_ms,
        )
    return SandboxResult(
        ok=True,
        stdout=payload.get("stdout", ""),
        stderr=payload.get("stderr", ""),
        duration_ms=duration_ms,
    )


def run_dataframe(input_path, output_path, code, timeout=35, profile: str = "ai"):
    """Backward-compatible helper used by existing tests."""
    result = run_sandboxed(
        code=code,
        input_paths={"df": str(input_path)},
        output_path=output_path,
        result_var="result",
        result_kind="table",
        profile=profile,
        timeout=timeout,
    )
    if not result.ok:
        raise RuntimeError(result.error or "沙箱执行失败")
    return {"ok": True, "stdout": result.stdout, "stderr": result.stderr}
