"""Adversarial test set for the AST white-list validator.

SPEC 5.3 / 7.3 require an *independent* assertion per attack sample; a single
blanket "malicious code is rejected" test is explicitly not acceptable.
"""

from __future__ import annotations

import pytest

from app.sandbox.validator import CodeRejected, ensure_safe, strip_injected_imports, validate

INJECTED = ("df", "pd", "np", "px", "go", "result")


def assert_rejected(code: str, expected_code: str | None = None) -> None:
    result = validate(code, INJECTED)
    assert not result.ok, f"expected rejection but code passed:\n{code}"
    assert result.issues, "rejection must carry at least one issue"
    assert all(i.message for i in result.issues), "every issue needs a message"
    if expected_code is not None:
        codes = {i.code for i in result.issues}
        assert expected_code in codes, f"expected issue code {expected_code}, got {codes}"


def assert_accepted(code: str) -> None:
    result = validate(code, INJECTED)
    assert result.ok, f"expected acceptance but got: {result.summary}\n{code}"


# --- SPEC 5.3 攻击样本清单（每条独立断言）--------------------------------


def test_reject_os_system():
    assert_rejected("os.system('rm -rf /')", "forbidden_call")


def test_reject_import_os():
    assert_rejected("import os\nos.system('ls')", "forbidden_syntax")


def test_reject_from_import():
    assert_rejected("from os import system", "forbidden_syntax")


def test_reject_dunder_builtins():
    assert_rejected("__builtins__", "dunder_name")


def test_reject_dunder_builtins_subscript():
    assert_rejected("__builtins__['eval']('1+1')", "dunder_name")


def test_reject_getattr_dunder_class():
    assert_rejected("getattr(df, '__class__')", "forbidden_call")


def test_reject_eval():
    assert_rejected("eval('1+1')", "forbidden_call")


def test_reject_open_etc_passwd():
    assert_rejected("open('/etc/passwd')", "forbidden_call")


def test_reject_exec_base64():
    assert_rejected("exec(base64.b64decode('cHJpbnQoMSk='))", "forbidden_call")


def test_reject_sandbox_escape_via_class_bases():
    assert_rejected("df.__class__.__bases__", "dunder_attribute")


def test_reject_sandbox_escape_via_subclasses():
    assert_rejected(
        "result = ().__class__.__bases__[0].__subclasses__()", "dunder_attribute"
    )


def test_reject_globals_lookup():
    assert_rejected("result = globals()", "forbidden_call")


def test_reject_globals_builtins_subscript():
    assert_rejected("globals()['__builtins__']", "dunder_subscript")


def test_reject_locals_lookup():
    assert_rejected("locals()", "forbidden_call")


def test_reject_import_dunder_call():
    assert_rejected("__import__('os')", "forbidden_call")


def test_reject_compile():
    assert_rejected("compile('1', '<s>', 'eval')", "forbidden_call")


def test_reject_setattr():
    assert_rejected("setattr(df, 'x', 1)", "forbidden_call")


def test_reject_dunder_subscript_string_key():
    assert_rejected("df['__class__']", "dunder_subscript")


def test_reject_dunder_dict_access():
    assert_rejected("result = df.__dict__", "dunder_attribute")


def test_reject_read_pickle_arbitrary_code_execution():
    assert_rejected("result = pd.read_pickle('/tmp/x.pkl')", "forbidden_call")


def test_reject_to_pickle():
    assert_rejected("df.to_pickle('/tmp/x.pkl')", "forbidden_call")


def test_reject_pandas_eval():
    assert_rejected("result = pd.eval('1+1')", "forbidden_call")


def test_reject_numpy_fromfile():
    assert_rejected("result = np.fromfile('/etc/passwd')", "forbidden_call")


def test_reject_socket_connect():
    assert_rejected("s.connect(('example.com', 80))", "forbidden_call")


def test_reject_subprocess_popen():
    assert_rejected("subprocess.Popen(['ls'])", "forbidden_call")


def test_reject_try_except_swallowing():
    assert_rejected("try:\n    result = df\nexcept Exception:\n    result = None", "forbidden_syntax")


def test_reject_with_statement():
    assert_rejected("with open('x') as f:\n    result = f", "forbidden_syntax")


def test_reject_class_definition():
    assert_rejected("class Evil:\n    pass", "forbidden_syntax")


def test_reject_global_statement():
    assert_rejected("def f():\n    global df\n    df = None", "forbidden_syntax")


def test_reject_del_statement():
    assert_rejected("del df", "forbidden_syntax")


def test_reject_decorator():
    assert_rejected("@staticmethod\ndef f():\n    return 1", "forbidden_syntax")


def test_reject_async_def():
    assert_rejected("async def f():\n    return 1", "forbidden_syntax")


def test_reject_walrus_rebinding_builtins():
    assert_rejected("(x := 1)", "forbidden_syntax")


def test_reject_lambda_hiding_eval():
    assert_rejected("f = lambda: eval('1')", "forbidden_call")


def test_reject_comprehension_hiding_getattr():
    assert_rejected("result = [getattr(df, c) for c in df.columns]", "forbidden_call")


def test_reject_syntax_error_is_reported_not_crash():
    assert_rejected("result = df[", "syntax_error")


def test_ensure_safe_raises_with_result():
    with pytest.raises(CodeRejected) as excinfo:
        ensure_safe("import os", INJECTED)
    assert excinfo.value.result.issues
    assert "import" in excinfo.value.result.summary


# --- 正常代码必须放行（防止校验器过严导致不可用）------------------------


def test_accept_basic_pandas_pipeline():
    assert_accepted(
        "df = df.dropna()\n"
        "df['city'] = df['city'].str.strip().str.lower()\n"
        "result = df.drop_duplicates()\n"
    )


def test_accept_groupby_and_agg():
    assert_accepted("result = df.groupby('city', as_index=False)['age'].mean()")


def test_accept_numpy_usage():
    assert_accepted("df['z'] = (df['age'] - np.mean(df['age'])) / np.std(df['age'])\nresult = df")


def test_accept_plotly_figure():
    assert_accepted("fig = px.bar(df, x='city', y='age', title='by city')")


def test_accept_control_flow_and_function_def():
    assert_accepted(
        "def clean(frame):\n"
        "    for col in frame.columns:\n"
        "        if frame[col].isna().mean() > 0.9:\n"
        "            frame = frame.drop(columns=[col])\n"
        "    return frame\n"
        "result = clean(df)\n"
    )


def test_accept_fstring_and_dict_literal():
    assert_accepted("result = {'rows': len(df), 'label': f'{len(df)} rows'}")


def test_accept_comprehension_over_columns():
    assert_accepted("num_cols = [c for c in df.columns if df[c].dtype != 'object']\nresult = df[num_cols]")


def test_strip_injected_imports_pandas_numpy_plotly():
    raw = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "import plotly.express as px\n"
        "from plotly import graph_objects as go\n"
        "result = df.dropna()\n"
    )
    cleaned = strip_injected_imports(raw)
    assert "import" not in cleaned
    assert_accepted(cleaned)


def test_strip_keeps_dangerous_imports():
    raw = "import pandas as pd\nimport os\nresult = df\n"
    cleaned = strip_injected_imports(raw)
    assert "import os" in cleaned
    assert_rejected(cleaned, "forbidden_syntax")


def test_strip_does_not_allow_from_pandas_dataframe():
    # Binding DataFrame is not an injected name — must remain and be rejected.
    raw = "from pandas import DataFrame\nresult = DataFrame()\n"
    cleaned = strip_injected_imports(raw)
    assert "from pandas" in cleaned or "DataFrame" in cleaned
    assert_rejected(cleaned, "forbidden_syntax")
