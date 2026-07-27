from pathlib import Path

import pandas as pd

from app.sandbox.runner import run_sandboxed
from app.sandbox.validator import strip_injected_imports, validate


def test_strip_removes_pandas_and_stdlib_imports():
    code = """
import pandas as pd
import numpy as np
from collections import Counter
import json
from pandas import DataFrame
result = {'n': len(df), 'c': dict(Counter(df['b']))}
"""
    stripped = strip_injected_imports(code)
    assert "import" not in stripped
    assert validate(stripped).ok


def test_analyze_code_with_habitual_imports_runs(tmp_path: Path):
    src = tmp_path / "in.parquet"
    out = tmp_path / "out.json"
    pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": ["x", "x", "y"]}).to_parquet(src)
    code = """
import pandas as pd
import numpy as np
from collections import Counter
import json
result = {
    "n": int(len(df)),
    "mean_a": float(df["a"].mean()),
    "counts": dict(Counter(df["b"])),
    "corr": df.corr(numeric_only=True).to_dict(),
}
"""
    result = run_sandboxed(
        code=code,
        input_paths={"df": str(src)},
        output_path=out,
        result_kind="stats",
        profile="ai",
    )
    assert result.ok, result.error
    text = out.read_text(encoding="utf-8")
    assert "mean_a" in text
    assert "counts" in text


def test_os_import_still_rejected():
    assert not validate("import os\nresult = df").ok
    assert not validate("__import__('os')\nresult = df").ok


def test_make_subplots_available_after_strip(tmp_path: Path):
    src = tmp_path / "in.parquet"
    out = tmp_path / "out.figure.json"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_parquet(src)
    code = """
from plotly.subplots import make_subplots
fig = make_subplots(rows=1, cols=2)
fig.add_trace(go.Scatter(x=df['a'], y=df['b'], mode='markers'), row=1, col=1)
"""
    result = run_sandboxed(
        code=code,
        input_paths={"df": str(src)},
        output_path=out,
        result_var="fig",
        result_kind="figure",
        profile="ai",
    )
    assert result.ok, result.error
    assert "data" in out.read_text(encoding="utf-8")
