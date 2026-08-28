import io
import json

import pytest

from jlkit.cli import main
from jlkit.core import (
    BadLine,
    JlkitError,
    collect_stats,
    compile_filter,
    get_path,
    infer_schema,
    iter_records,
    open_source,
    schema_errors,
)

SAMPLE = '\n'.join([
    '{"a": 1, "b": {"c": "x"}}',
    '   ',
    '{"a": 2, "b": {"c": "y"}}',
    'not json',
    '{"a": 3}',
]) + '\n'


def test_iter_records_skips_blank_and_bad():
    recs = list(iter_records(io.StringIO(SAMPLE)))
    assert [obj["a"] for _, obj in recs] == [1, 2, 3]


def test_iter_records_yield_bad():
    recs = list(iter_records(io.StringIO(SAMPLE), on_bad="yield"))
    bad = [r for _, r in recs if isinstance(r, BadLine)]
    assert len(bad) == 1 and bad[0].lineno == 4


def test_iter_records_raise():
    with pytest.raises(ValueError):
        list(iter_records(io.StringIO(SAMPLE), on_bad="raise"))


def test_get_path():
    assert get_path({"b": {"c": 5}}, "b.c") == (True, 5)
    assert get_path({"b": {}}, "b.c") == (False, None)


def test_cli_head(tmp_path, capsys):
    f = tmp_path / "d.jsonl"
    f.write_text(SAMPLE)
    assert main(["head", "2", str(f)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2 and '"a":1' in out[0]


def test_cli_tail(tmp_path, capsys):
    f = tmp_path / "d.jsonl"
    f.write_text(SAMPLE)
    assert main(["tail", "1", str(f)]) == 0
    assert capsys.readouterr().out.strip() == '{"a":3}'


def test_cli_select(tmp_path, capsys):
    f = tmp_path / "d.jsonl"
    f.write_text(SAMPLE)
    assert main(["select", "a,b.c", str(f)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == '{"a":1,"b.c":"x"}'
    assert lines[2] == '{"a":3}'


PEOPLE = '\n'.join([
    '{"name": "ana", "age": 34, "country": "US", "tags": ["a", "b"]}',
    '{"name": "bo", "age": 22, "country": "DE"}',
    '{"name": "cy", "age": 41, "country": "US", "tags": []}',
]) + '\n'


def test_compile_filter_cmp_and_bool():
    pred = compile_filter('age > 30 and country == "US"')
    objs = [json.loads(l) for l in PEOPLE.strip().splitlines()]
    assert [o["name"] for o in objs if pred(o)] == ["ana", "cy"]


def test_compile_filter_exists_contains_not_paren():
    assert compile_filter("tags exists")({"tags": []}) is True
    assert compile_filter("tags exists")({}) is False
    assert compile_filter('tags contains "a"')({"tags": ["a"]}) is True
    assert compile_filter("not (age < 30)")({"age": 40}) is True
    assert compile_filter("a.b == 1")({"a": {"b": 1}}) is True


def test_compile_filter_bad_expr():
    with pytest.raises(ValueError):
        compile_filter("age >")


def test_cli_filter(tmp_path, capsys):
    f = tmp_path / "p.jsonl"
    f.write_text(PEOPLE)
    assert main(["filter", "age >= 34", str(f)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2 and '"name":"ana"' in out[0]


def test_collect_stats():
    recs = list(iter_records(io.StringIO(PEOPLE)))
    s = collect_stats(recs)
    assert s["records"] == 3
    assert s["fields"]["age"]["presence"] == 1.0
    assert s["fields"]["age"]["numeric"]["min"] == 22
    assert s["fields"]["age"]["numeric"]["max"] == 41
    assert s["fields"]["country"]["string_cardinality"] == 2
    assert s["fields"]["name"]["presence"] == 1.0
    assert s["fields"]["tags"]["presence"] == pytest.approx(2 / 3, rel=1e-3)


def test_infer_schema_and_validate():
    recs = list(iter_records(io.StringIO(PEOPLE)))
    schema = infer_schema(recs)
    assert schema["type"] == "object"
    assert schema["properties"]["age"]["type"] == "integer"
    assert "name" in schema["required"] and "tags" not in schema["required"]
    assert schema_errors(schema, {"name": "z", "age": 5, "country": "US"}) == []
    errs = schema_errors(schema, {"name": "z", "age": "old", "country": "US"})
    assert errs and "age" in errs[0]


def test_cli_validate_malformed(tmp_path, capsys):
    f = tmp_path / "d.jsonl"
    f.write_text(SAMPLE)
    assert main(["validate", str(f)]) == 1
    assert "line 4" in capsys.readouterr().err


def test_cli_validate_with_schema(tmp_path, capsys):
    data = tmp_path / "p.jsonl"
    data.write_text(PEOPLE)
    schema_file = tmp_path / "s.json"
    recs = list(iter_records(io.StringIO(PEOPLE)))
    schema_file.write_text(json.dumps(infer_schema(recs)))
    assert main(["validate", "--schema", str(schema_file), str(data)]) == 0

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"name": "x", "age": "nope", "country": "US"}\n')
    assert main(["validate", "--schema", str(schema_file), str(bad)]) == 1


def test_open_source_missing_file_raises_jlkiterror(tmp_path):
    with pytest.raises(JlkitError):
        open_source(str(tmp_path / "does-not-exist.jsonl"))


def test_cli_missing_file_is_clean_error(tmp_path, capsys):
    rc = main(["select", "a", str(tmp_path / "nope.jsonl")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "nope.jsonl" in err and "Traceback" not in err


def test_cli_limit(tmp_path, capsys):
    f = tmp_path / "p.jsonl"
    f.write_text(PEOPLE)
    assert main(["select", "name", "--limit", "1", str(f)]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 1
