from pathlib import Path

from app.schema_resolve import (
    probe_file_schema,
    resolve_node_output_schema,
    resolve_table_input_schemas,
    resolve_upstream_schema,
    selected_columns_from_params,
)


def test_probe_file_schema_csv(tmp_path: Path):
    src = tmp_path / "t.csv"
    src.write_text("name,age,city\nalice,30,SH\nbob,25,BJ\n", encoding="utf-8")
    schema = probe_file_schema(src)
    names = {c.name: c.kind for c in schema.columns}
    assert set(names) == {"name", "age", "city"}
    assert names["age"] == "numeric"


def test_resolve_upstream_from_file_input(tmp_path: Path):
    src = tmp_path / "t.csv"
    src.write_text("a,b\n1,x\n2,y\n", encoding="utf-8")
    graph = {
        "nodes": [
            {"id": "src", "type": "file_input", "data": {"params": {"path": str(src)}}},
            {"id": "clean", "type": "ai_clean", "data": {"params": {"columns": ["a"]}}},
        ],
        "edges": [
            {
                "id": "e1",
                "source": "src",
                "sourceHandle": "table_out",
                "target": "clean",
                "targetHandle": "table_in",
            }
        ],
    }
    out = resolve_node_output_schema(graph, "src")
    assert out is not None
    assert {c.name for c in out.columns} == {"a", "b"}

    up, source_id, port = resolve_upstream_schema(graph, "clean")
    assert source_id == "src"
    assert port == "table_out"
    assert up is not None
    assert [c.name for c in up.columns] == ["a", "b"]


def test_selected_columns_from_params():
    assert selected_columns_from_params(
        {"columns": ["a", "b"], "x": "a", "y": "c", "color": ""}
    ) == ["a", "b", "c"]


def test_resolve_upstream_walks_through_unrun_clean(tmp_path: Path):
    """filter ← ai_clean ← file_input should still get columns before any run."""
    src = tmp_path / "t.csv"
    src.write_text("Survived,Age,Fare\n1,22,7.25\n0,38,71.2\n", encoding="utf-8")
    graph = {
        "nodes": [
            {"id": "src", "type": "file_input", "data": {"params": {"path": str(src)}}},
            {"id": "clean", "type": "ai_clean", "data": {"params": {"intent": "清洗"}}},
            {"id": "filter", "type": "filter", "data": {"params": {}}},
        ],
        "edges": [
            {
                "source": "src",
                "sourceHandle": "table_out",
                "target": "clean",
                "targetHandle": "table_in",
            },
            {
                "source": "clean",
                "sourceHandle": "table_out",
                "target": "filter",
                "targetHandle": "table_in",
            },
        ],
    }
    up, source_id, _port = resolve_upstream_schema(graph, "filter")
    assert up is not None
    assert {c.name for c in up.columns} == {"Survived", "Age", "Fare"}
    assert source_id == "src"


def test_schema_resolve_api(tmp_path: Path):
    from app import create_app

    src = tmp_path / "t.csv"
    src.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
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
        "nodes": [
            {"id": "src", "type": "file_input", "data": {"params": {"path": str(src)}}},
            {"id": "chart", "type": "ai_chart", "data": {"params": {}}},
        ],
        "edges": [
            {
                "source": "src",
                "sourceHandle": "table_out",
                "target": "chart",
                "targetHandle": "table_in",
            }
        ],
    }
    res = c.post("/api/schema/resolve", json={"graph": graph, "node_id": "chart"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["source_node_id"] == "src"
    assert {col["name"] for col in body["columns"]} == {"x", "y"}
    assert all("kind" in col and "dtype" in col for col in body["columns"])

    src_res = c.post("/api/schema/resolve", json={"graph": graph, "node_id": "src"})
    assert src_res.status_code == 200
    assert src_res.get_json()["output"]["row_count"] >= 2


def test_join_resolves_left_and_right_schemas(tmp_path: Path):
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("id,name\n1,a\n", encoding="utf-8")
    right.write_text("id,score\n1,9\n", encoding="utf-8")
    graph = {
        "nodes": [
            {"id": "l", "type": "file_input", "data": {"params": {"path": str(left)}}},
            {"id": "r", "type": "file_input", "data": {"params": {"path": str(right)}}},
            {"id": "j", "type": "join", "data": {"params": {"how": "inner"}}},
        ],
        "edges": [
            {
                "source": "l",
                "sourceHandle": "table_out",
                "target": "j",
                "targetHandle": "left",
            },
            {
                "source": "r",
                "sourceHandle": "table_out",
                "target": "j",
                "targetHandle": "right",
            },
        ],
    }
    schemas = resolve_table_input_schemas(graph, "j")
    assert {c.name for c in schemas["left"].columns} == {"id", "name"}
    assert {c.name for c in schemas["right"].columns} == {"id", "score"}

    from app import create_app

    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "db.sqlite"),
            "CACHE_DIR": str(tmp_path / "cache"),
            "SECRET_DIR": str(tmp_path / "secret"),
        }
    )
    body = app.test_client().post(
        "/api/schema/resolve", json={"graph": graph, "node_id": "j"}
    ).get_json()
    assert {c["name"] for c in body["inputs"]["left"]["columns"]} == {"id", "name"}
    assert {c["name"] for c in body["inputs"]["right"]["columns"]} == {"id", "score"}


def test_join_output_schema_merged_before_run(tmp_path: Path):
    left = tmp_path / "orders.csv"
    right = tmp_path / "customers.csv"
    left.write_text("order_id,customer_id,amount\n1,C01,99\n", encoding="utf-8")
    right.write_text("customer_id,segment,city\nC01,企业,上海\n", encoding="utf-8")
    graph = {
        "nodes": [
            {"id": "orders", "type": "file_input", "data": {"params": {"path": str(left)}}},
            {"id": "customers", "type": "file_input", "data": {"params": {"path": str(right)}}},
            {
                "id": "join",
                "type": "join",
                "data": {
                    "params": {
                        "how": "left",
                        "left_on": ["customer_id"],
                        "right_on": ["customer_id"],
                    }
                },
            },
            {
                "id": "gb",
                "type": "groupby",
                "data": {"params": {"by": ["segment"], "values": ["amount"], "aggs": ["sum"]}},
            },
        ],
        "edges": [
            {
                "source": "orders",
                "sourceHandle": "table_out",
                "target": "join",
                "targetHandle": "left",
            },
            {
                "source": "customers",
                "sourceHandle": "table_out",
                "target": "join",
                "targetHandle": "right",
            },
            {
                "source": "join",
                "sourceHandle": "table_out",
                "target": "gb",
                "targetHandle": "table_in",
            },
        ],
    }
    joined = resolve_node_output_schema(graph, "join")
    assert joined is not None
    names = {c.name for c in joined.columns}
    assert "segment" in names
    assert "amount" in names
    assert "customer_id" in names

    up, source_id, _ = resolve_upstream_schema(graph, "gb")
    assert source_id == "join"
    assert up is not None
    assert "segment" in {c.name for c in up.columns}


def test_orders_join_example_groupby_sees_segment():
    from app import create_app
    from app.examples import instantiate_example

    app = create_app({"TESTING": True})
    with app.app_context():
        payload = instantiate_example(
            "130-orders-join", instance_path=app.instance_path
        )
    graph = payload["graph"]
    client = app.test_client()
    body = client.post(
        "/api/schema/resolve", json={"graph": graph, "node_id": "n_groupby"}
    ).get_json()
    names = {c["name"] for c in body["columns"]}
    assert "segment" in names
    assert "amount" in names
