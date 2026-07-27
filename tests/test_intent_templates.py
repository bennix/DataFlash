from app import create_app
from app.ai.intent_templates import fill_template, get_template, templates_for
from app.registry import all_specs


def test_ai_nodes_have_templates():
    min_counts = {
        "ai_clean": 12,
        "ai_analyze": 10,
        "ai_chart": 12,
        "ai_report": 7,
        "filter": 10,
    }
    for node_type, minimum in min_counts.items():
        tpls = templates_for(node_type)
        assert len(tpls) >= minimum, f"{node_type} templates {len(tpls)} < {minimum}"
        ids = [t["id"] for t in tpls]
        assert len(ids) == len(set(ids)), f"duplicate template id in {node_type}"
        for t in tpls:
            assert t["id"] and t["label"] and t["body"]
            assert isinstance(t["slots"], list)
            for slot in t["slots"]:
                assert slot["key"] and slot["type"] in {"column", "columns", "text"}


def test_new_templates_exist():
    assert get_template("ai_clean", "clip_outliers")
    assert get_template("ai_analyze", "crosstab")
    assert get_template("ai_chart", "heatmap")
    assert get_template("ai_report", "exec_summary")
    assert get_template("filter", "date_window")


def test_fill_template_columns_and_leave_empty():
    body = "删除字段 {{columns}} 为空的行，可选分组 {{group}}"
    filled = fill_template(body, {"columns": ["Age", "Fare"], "group": ""})
    assert "Age、Fare" in filled
    assert "（待选）" in filled
    assert "{{group}}" not in filled


def test_chart_scatter_template():
    tpl = get_template("ai_chart", "scatter")
    assert tpl is not None
    text = fill_template(tpl["body"], {"x": "Age", "y": "Fare", "color": "Sex"})
    assert "Age" in text and "Fare" in text and "Sex" in text
    assert "{{" not in text


def test_nodes_api_public_includes_templates(tmp_path):
    create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "db.sqlite"),
            "CACHE_DIR": str(tmp_path / "cache"),
            "SECRET_DIR": str(tmp_path / "secret"),
        }
    )
    by_type = {s.type: s.public() for s in all_specs()}
    assert by_type["ai_clean"]["intent_templates"]
    assert by_type["file_input"]["intent_templates"] == []


def test_nodes_http_includes_intent_templates(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "db.sqlite"),
            "CACHE_DIR": str(tmp_path / "cache"),
            "SECRET_DIR": str(tmp_path / "secret"),
        }
    )
    client = app.test_client()
    nodes = client.get("/api/nodes").get_json()
    chart = next(n for n in nodes if n["type"] == "ai_chart")
    assert any(t["id"] == "scatter" for t in chart["intent_templates"])
