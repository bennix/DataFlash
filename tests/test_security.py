import pytest
from app.security import validate_code, UnsafeCode

@pytest.mark.parametrize("code", [
    "import os\nos.system('id')", "__builtins__", "getattr(df, '__class__')",
    "eval('1+1')", "open('/etc/passwd')", "exec(base64.b64decode(''))",
    "df.__class__.__bases__", "from os import system", "__import__('os')",
])
def test_adversarial_code_is_blocked(code):
    with pytest.raises(UnsafeCode): validate_code(code)

def test_safe_dataframe_code_is_allowed():
    assert validate_code("result = df.dropna()\nresult['total'] = result['a'] * 2")
