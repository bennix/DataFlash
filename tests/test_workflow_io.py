from app import create_app


def test_save_list_load_export_import(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "db.sqlite"),
            "CACHE_DIR": str(tmp_path / "cache"),
            "SECRET_DIR": str(tmp_path / "secret"),
        }
    )
    c = app.test_client()
    graph = {
        "format_version": 2,
        "nodes": [{"id": "a", "type": "preview", "data": {"params": {}}}],
        "edges": [],
    }
    created = c.post("/api/workflows", json={"name": "我的流程", "graph": graph}).get_json()
    assert created["id"]
    assert c.put(
        f"/api/workflows/{created['id']}",
        json={"name": "我的流程 v2", "graph": graph},
    ).status_code == 204

    listed = c.get("/api/workflows").get_json()
    assert any(w["id"] == created["id"] and w["name"] == "我的流程 v2" for w in listed)

    loaded = c.get(f"/api/workflows/{created['id']}").get_json()
    assert loaded["graph"]["nodes"][0]["id"] == "a"

    exported = c.get(f"/api/workflows/{created['id']}/export").get_json()
    assert exported["format"] == "dataflash.flow"
    assert exported["name"] == "我的流程 v2"
    assert exported["graph"]["nodes"]

    imported = c.post(
        "/api/workflows/import",
        json={"name": "从文件导入", "graph": exported["graph"]},
    )
    assert imported.status_code == 201
    assert imported.get_json()["name"] == "从文件导入"
    assert imported.get_json()["graph"]["nodes"][0]["type"] == "preview"
