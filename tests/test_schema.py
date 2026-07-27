from app.schema import infer_schema, mask_pii
import pandas as pd


def test_infer_numeric_and_categorical():
    df = pd.DataFrame(
        {
            "age": [18, 25, 40, 33],
            "city": ["北京", "上海", "北京", "广州"],
            "flag": [0, 1, 0, 1],
        }
    )
    schema = infer_schema(df)
    kinds = {c.name: c.kind for c in schema.columns}
    assert kinds["age"] == "numeric"
    assert kinds["city"] == "categorical"
    assert kinds["flag"] in {"boolean", "categorical"}


def test_mask_pii_phone_and_email():
    assert "<masked:phone>" in mask_pii("联系我 13812345678 谢谢")
    assert "<masked:email>" in mask_pii("user@example.com")


def test_schema_fingerprint_stable():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    s1 = infer_schema(df)
    s2 = infer_schema(df)
    assert s1.fingerprint() == s2.fingerprint()
