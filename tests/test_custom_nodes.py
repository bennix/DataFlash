"""Custom sandboxed node upload / load / debug."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from app import create_app
from app.custom_nodes.loader import validate_package_dir
from app.custom_nodes.package import install_from_files
from app.registry import get_spec


def _app(tmp_path):
    instance = tmp_path / "instance"
    instance.mkdir()
    return create_app(
        {
            "TESTING": True,
            "INSTANCE_PATH": str(instance),
            "DATABASE": str(tmp_path / "db.sqlite"),
            "CACHE_DIR": str(tmp_path / "cache"),
            "SECRET_DIR": str(tmp_path / "secret"),
        }
    )


def test_sample_loads_into_registry(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        spec = get_spec("custom.scale_numeric")
        assert spec is not None
        assert spec.custom is True
        assert spec.code_profile == "ai"
        assert spec.is_ai is False
        assert spec.build_code is not None
        pub = spec.public()
        assert pub["custom"] is True
        assert pub["source"] == "user"

        ai = get_spec("custom.ai_flag_rows")
        assert ai is not None
        assert ai.custom is True
        assert ai.is_ai is True
        assert ai.build_code is None
        assert ai.ai_prompt_hint
        assert ai.intent_templates
        assert ai.public()["is_ai"] is True
        assert ai.public()["intent_templates"]


def test_nodes_api_includes_sample(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    nodes = c.get("/api/nodes").get_json()
    types = {n["type"] for n in nodes}
    assert "custom.scale_numeric" in types
    sample = next(n for n in nodes if n["type"] == "custom.scale_numeric")
    assert sample["custom"] is True


def test_upload_zip_and_list(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    manifest = {
        "id": "double_col",
        "label": "Double",
        "result_kind": "table",
        "params_schema": [{"key": "factor", "type": "number", "label": "f", "default": 2}],
    }
    transform = "result = df.copy()\nresult['x'] = result['x'] * float(params.get('factor') or 2)\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("double_col/manifest.json", json.dumps(manifest))
        zf.writestr("double_col/transform.py", transform)
    data = buf.getvalue()
    resp = c.post(
        "/api/custom-nodes/upload",
        data={"file": (io.BytesIO(data), "double_col.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["type"] == "custom.double_col"
    listed = c.get("/api/custom-nodes").get_json()
    ids = {i["id"] for i in listed}
    assert "double_col" in ids
    assert get_spec("custom.double_col") is not None


def test_forbid_override_builtin(tmp_path):
    app = _app(tmp_path)
    instance = Path(app.instance_path)
    with pytest.raises(ValueError, match="冲突|覆盖"):
        install_from_files(
            instance,
            manifest_text=json.dumps(
                {
                    "id": "file_input",
                    "label": "Hack",
                    "result_kind": "table",
                }
            ),
            transform_text="result = df\n",
        )


def test_ast_rejects_open(tmp_path):
    app = _app(tmp_path)
    instance = Path(app.instance_path)
    with pytest.raises(ValueError, match="安全校验"):
        install_from_files(
            instance,
            manifest_text=json.dumps(
                {"id": "evil_open", "label": "Evil", "result_kind": "table"}
            ),
            transform_text="f = open('/etc/passwd')\nresult = df\n",
        )


def test_debug_success_and_failure(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    ok = c.post(
        "/api/custom-nodes/scale_numeric/debug",
        json={
            "csv_text": "a,b\n1,10\n2,20\n",
            "params": {"columns": ["b"], "factor": 3},
        },
    )
    assert ok.status_code == 200, ok.get_json()
    payload = ok.get_json()
    assert payload["ok"] is True
    assert payload["preview"]["row_count"] == 2
    assert payload["preview"]["rows"][0]["b"] in ("30", "30.0")

    # Bad transform installed temporarily
    install_from_files(
        Path(app.instance_path),
        manifest_text=json.dumps(
            {"id": "boom", "label": "Boom", "result_kind": "table"}
        ),
        transform_text="result = missing_name\n",
    )
    bad = c.post(
        "/api/custom-nodes/boom/debug",
        json={"csv_text": "x\n1\n", "params": {}},
    )
    assert bad.status_code == 422
    body = bad.get_json()
    assert body["ok"] is False
    assert body.get("error")


def test_delete_unregisters(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    install_from_files(
        Path(app.instance_path),
        manifest_text=json.dumps(
            {"id": "temp_node", "label": "Temp", "result_kind": "table"}
        ),
        transform_text="result = df\n",
    )
    assert get_spec("custom.temp_node") is not None
    resp = c.delete("/api/custom-nodes/temp_node")
    assert resp.status_code == 204
    assert get_spec("custom.temp_node") is None


def test_sample_zip_download(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    resp = c.get("/api/custom-nodes/sample")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
    assert any(n.endswith("manifest.json") for n in names)
    assert any(n.endswith("transform.py") for n in names)

    ai = c.get("/api/custom-nodes/sample?id=ai_flag_rows")
    assert ai.status_code == 200
    with zipfile.ZipFile(io.BytesIO(ai.data)) as zf:
        names = zf.namelist()
    assert any("ai_flag_rows" in n and n.endswith("manifest.json") for n in names)
    assert any(n.endswith("prompt.md") for n in names)


def test_validate_bundled_sample():
    sample = Path(__file__).resolve().parents[1] / "app/custom_nodes/sample_scale_numeric"
    meta, code = validate_package_dir(sample)
    assert meta["id"] == "scale_numeric"
    assert "result" in code


def test_validate_ai_sample_without_transform():
    sample = Path(__file__).resolve().parents[1] / "app/custom_nodes/sample_ai_flag_rows"
    meta, code = validate_package_dir(sample)
    assert meta["id"] == "ai_flag_rows"
    assert meta.get("is_ai") is True
    assert code == ""


def test_ai_custom_debug_uses_mock(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    resp = c.post(
        "/api/custom-nodes/ai_flag_rows/debug",
        json={
            "csv_text": "Fare,Sex\n10,male\n80,female\n",
            "params": {"intent": "标记高票价", "columns": ["Fare"]},
        },
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["preview"]["row_count"] == 2
    flags = [row.get("Flag") for row in body["preview"]["rows"]]
    assert any(str(f).lower() in {"true", "1"} for f in flags)


def test_upload_ai_custom_package(tmp_path):
    app = _app(tmp_path)
    c = app.test_client()
    manifest = {
        "id": "ai_tag_demo",
        "label": "AI Tag Demo",
        "is_ai": True,
        "result_kind": "table",
        "params_schema": [
            {"key": "intent", "type": "textarea", "label": "意图", "required": True}
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ai_tag_demo/manifest.json", json.dumps(manifest))
        zf.writestr("ai_tag_demo/prompt.md", "新增列 Tag。")
    resp = c.post(
        "/api/custom-nodes/upload",
        data={"file": (io.BytesIO(buf.getvalue()), "ai_tag_demo.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    spec = get_spec("custom.ai_tag_demo")
    assert spec is not None
    assert spec.is_ai is True
    assert spec.build_code is None
