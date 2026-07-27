from app import create_app
from app.examples import instantiate_example, list_examples

EXPECTED_EXAMPLE_IDS = {
    "110-analysis-visualization",
    "120-sales-groupby",
    "130-orders-join",
    "140-hr-attrition",
    "150-web-trend",
    "160-shop-multi-join",
    "170-support-sla",
    "180-budget-variance",
}


def test_list_includes_all_templates():
    ids = {e["id"] for e in list_examples()}
    assert EXPECTED_EXAMPLE_IDS <= ids


def test_instantiate_resolves_dataset_path(tmp_path):
    payload = instantiate_example(
        "110-analysis-visualization", instance_path=tmp_path
    )
    graph = payload["graph"]
    file_node = next(n for n in graph["nodes"] if n["type"] == "file_input")
    path = file_node["data"]["params"]["path"]
    assert path.endswith("passengers.csv")
    assert "{{" not in path
    assert (tmp_path / "uploads" / "examples").exists()
    export_node = next(n for n in graph["nodes"] if n["type"] == "export")
    assert export_node["data"]["params"]["path"].endswith(".pdf")


def test_instantiate_all_examples_resolve_placeholders(tmp_path):
    for example_id in sorted(EXPECTED_EXAMPLE_IDS):
        payload = instantiate_example(example_id, instance_path=tmp_path / example_id)
        assert payload["graph"]["nodes"]
        for node in payload["graph"]["nodes"]:
            params = (node.get("data") or {}).get("params") or {}
            for value in params.values():
                if isinstance(value, str):
                    assert "{{" not in value, f"{example_id} unresolved: {value}"


def test_instantiate_join_copies_extra_dataset(tmp_path):
    payload = instantiate_example("130-orders-join", instance_path=tmp_path)
    paths = [
        n["data"]["params"]["path"]
        for n in payload["graph"]["nodes"]
        if n["type"] == "file_input"
    ]
    assert len(paths) == 2
    assert any(p.endswith("orders.csv") for p in paths)
    assert any(p.endswith("customers.csv") for p in paths)
    assert all("{{" not in p for p in paths)


def test_examples_api(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "db.sqlite"),
            "CACHE_DIR": str(tmp_path / "cache"),
            "SECRET_DIR": str(tmp_path / "secret"),
        }
    )
    client = app.test_client()
    listed = client.get("/api/examples")
    assert listed.status_code == 200
    assert any(x["id"] == "110-analysis-visualization" for x in listed.get_json())

    made = client.post("/api/examples/110-analysis-visualization/instantiate")
    assert made.status_code == 201
    body = made.get_json()
    assert body["workflow"]["name"] == "乘客生存分析可视化"
    assert body["workflow"]["graph"]["nodes"]
    file_node = next(n for n in body["workflow"]["graph"]["nodes"] if n["type"] == "file_input")
    assert file_node["data"]["params"]["path"]


def test_examples_and_nodes_locale_en(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "db.sqlite"),
            "CACHE_DIR": str(tmp_path / "cache"),
            "SECRET_DIR": str(tmp_path / "secret"),
        }
    )
    client = app.test_client()
    listed = client.get("/api/examples?locale=en")
    assert listed.status_code == 200
    item = next(x for x in listed.get_json() if x["id"] == "110-analysis-visualization")
    assert item["title"] == "Passenger Survival Analysis"

    nodes = client.get("/api/nodes?locale=en").get_json()
    file_input = next(n for n in nodes if n["type"] == "file_input")
    assert file_input["label"] == "File Input"
    assert file_input["locale"] == "en"

    made = client.post(
        "/api/examples/110-analysis-visualization/instantiate?locale=en"
    )
    assert made.status_code == 201
    body = made.get_json()
    assert body["title"] == "Passenger Survival Analysis"
    clean = next(n for n in body["workflow"]["graph"]["nodes"] if n["type"] == "ai_clean")
    assert clean["data"]["label"] == "Clean missing values"
    assert "Drop rows" in clean["data"]["params"]["intent"]
