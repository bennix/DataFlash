import pytest
from app.ai import ModelContractError, parse_model_payload

def test_parse_model_payload_accepts_fenced_json_and_python():
    content='''```json
{"code":"```python\\nresult = df.dropna()\\n```","explanation":"删除空值","assumptions":[]}
```'''
    result=parse_model_payload(content)
    assert result["code"]=="result = df.dropna()"

def test_parse_model_payload_ignores_leading_explanation():
    result=parse_model_payload('处理方案如下：\n{"code":"result = df.copy()", "explanation":"保留数据"}')
    assert result["code"]=="result = df.copy()"
    assert result["assumptions"]==[]

def test_parse_model_payload_requires_code():
    with pytest.raises(ModelContractError,match="实际字段：explanation"): parse_model_payload('{"explanation":"missing"}')

def test_parse_model_payload_rejects_empty_code():
    with pytest.raises(ModelContractError): parse_model_payload('{"code":"  ","explanation":"empty"}')
