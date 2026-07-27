import pandas as pd
import pytest

from app.nodes.groupby_node import groupby_frame
from app.nodes.join_node import join_frames


def test_join_inner_and_left():
    left = pd.DataFrame({"id": [1, 2, 3], "v": ["a", "b", "c"]})
    right = pd.DataFrame({"id": [1, 2, 4], "w": [10, 20, 40]})
    inner, _ = join_frames(left, right, how="inner", left_on=["id"], right_on=["id"])
    assert len(inner) == 2
    assert set(inner["id"]) == {1, 2}

    left_j, _ = join_frames(left, right, how="left", left_on=["id"], right_on=["id"])
    assert len(left_j) == 3
    assert left_j.loc[left_j["id"] == 3, "w"].isna().all()


def test_join_multi_key_and_suffixes():
    left = pd.DataFrame({"k1": [1, 1], "k2": ["x", "y"], "val": [1, 2]})
    right = pd.DataFrame({"k1": [1, 1], "k2": ["x", "z"], "val": [9, 8]})
    out, _ = join_frames(
        left,
        right,
        how="inner",
        left_on=["k1", "k2"],
        right_on=["k1", "k2"],
        suffixes=("_l", "_r"),
    )
    assert len(out) == 1
    assert "val_l" in out.columns and "val_r" in out.columns
    assert int(out.iloc[0]["val_l"]) == 1
    assert int(out.iloc[0]["val_r"]) == 9


def test_join_right_keys_default_to_left():
    left = pd.DataFrame({"id": [1], "a": [1]})
    right = pd.DataFrame({"id": [1], "b": [2]})
    out, _ = join_frames(left, right, how="inner", left_on=["id"], right_on=[])
    assert list(out.columns) == ["id", "a", "b"]


def test_join_cross_and_missing_key_errors():
    left = pd.DataFrame({"a": [1, 2]})
    right = pd.DataFrame({"b": [3]})
    cross, warns = join_frames(left, right, how="cross")
    assert len(cross) == 2
    assert set(cross.columns) == {"a", "b"}

    with pytest.raises(ValueError, match="连接键"):
        join_frames(left, right, how="inner")

    with pytest.raises(ValueError, match="左表缺少"):
        join_frames(left, right, how="inner", left_on=["missing"], right_on=["b"])


def test_join_validate_one_to_one():
    left = pd.DataFrame({"id": [1, 1], "a": [1, 2]})
    right = pd.DataFrame({"id": [1], "b": [9]})
    with pytest.raises(ValueError, match="校验"):
        join_frames(
            left, right, how="inner", left_on=["id"], right_on=["id"], validate="one_to_one"
        )


def test_join_indicator_and_empty():
    left = pd.DataFrame({"id": [1], "a": [1]})
    right = pd.DataFrame({"id": [2], "b": [2]})
    out, _ = join_frames(
        left, right, how="outer", left_on=["id"], right_on=["id"], indicator=True
    )
    assert "_merge" in out.columns
    assert len(out) == 2

    empty_l = pd.DataFrame({"id": pd.Series(dtype=int), "a": pd.Series(dtype=int)})
    empty_r = pd.DataFrame({"id": pd.Series(dtype=int), "b": pd.Series(dtype=int)})
    out2, _ = join_frames(empty_l, empty_r, how="inner", left_on=["id"], right_on=["id"])
    assert len(out2) == 0


def test_groupby_mean_and_multi_agg():
    df = pd.DataFrame(
        {
            "g": ["a", "a", "b"],
            "x": [1.0, 3.0, 5.0],
            "y": [10, 20, 30],
        }
    )
    out, _ = groupby_frame(df, by=["g"], values=["x"], aggs=["mean"])
    assert len(out) == 2
    assert "x_mean" in out.columns
    row_a = out.loc[out["g"] == "a", "x_mean"].iloc[0]
    assert row_a == pytest.approx(2.0)

    multi, _ = groupby_frame(df, by=["g"], values=["x", "y"], aggs=["sum", "count"])
    assert "x_sum" in multi.columns and "y_count" in multi.columns


def test_groupby_size_without_values():
    df = pd.DataFrame({"g": ["a", "a", "b"], "x": [1, 2, 3]})
    out, _ = groupby_frame(df, by=["g"], values=[], aggs=["size"])
    assert list(out.columns) == ["g", "size"]
    assert int(out.loc[out["g"] == "a", "size"].iloc[0]) == 2


def test_groupby_dropna_and_errors():
    df = pd.DataFrame({"g": ["a", None, "a"], "x": [1.0, 2.0, 3.0]})
    keep, _ = groupby_frame(df, by=["g"], values=["x"], aggs=["sum"], dropna=False)
    assert keep["g"].isna().any()

    drop, _ = groupby_frame(df, by=["g"], values=["x"], aggs=["sum"], dropna=True)
    assert not drop["g"].isna().any()

    with pytest.raises(ValueError, match="分组字段"):
        groupby_frame(df, by=[], values=["x"], aggs=["mean"])

    with pytest.raises(ValueError, match="重复"):
        groupby_frame(df, by=["g"], values=["g"], aggs=["count"])


def test_nodes_execute_via_engine(tmp_path):
    from app.engine.executor import execute

    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("id,v\n1,a\n2,b\n", encoding="utf-8")
    right.write_text("id,w\n1,10\n2,20\n", encoding="utf-8")
    graph = {
        "nodes": [
            {"id": "l", "type": "file_input", "data": {"params": {"path": str(left)}}},
            {"id": "r", "type": "file_input", "data": {"params": {"path": str(right)}}},
            {
                "id": "j",
                "type": "join",
                "data": {
                    "params": {
                        "how": "inner",
                        "left_on": ["id"],
                        "right_on": ["id"],
                    }
                },
            },
            {
                "id": "g",
                "type": "groupby",
                "data": {
                    "params": {
                        "by": ["v"],
                        "values": ["w"],
                        "aggs": ["sum"],
                    }
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "l",
                "sourceHandle": "table_out",
                "target": "j",
                "targetHandle": "left",
            },
            {
                "id": "e2",
                "source": "r",
                "sourceHandle": "table_out",
                "target": "j",
                "targetHandle": "right",
            },
            {
                "id": "e3",
                "source": "j",
                "sourceHandle": "table_out",
                "target": "g",
                "targetHandle": "table_in",
            },
        ],
    }
    events = []
    _, outputs = execute(
        graph,
        tmp_path / "cache",
        lambda *args: events.append(args),
        configured=True,
    )
    assert "g" in outputs
    result = outputs["g"]
    assert isinstance(result, pd.DataFrame)
    assert "w_sum" in result.columns
    assert len(result) == 2
