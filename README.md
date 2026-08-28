# jltool

A JSONL-native command-line toolkit. `jq` is a per-line expression language and
`jless`/`jnv` are viewers — none give ergonomic **dataset-level** operations on
newline-delimited JSON, the format every LLM / eval / log / data pipeline emits.
`jltool` does.

Everything streams: it never loads the whole file and it tolerates malformed
lines (reporting them by number where that matters).

> Status: **beta** (v0.1.0). All seven subcommands work; PyPI release imminent.

## Install

```
uvx jltool --help      # or: pipx install jltool
```

## Usage

```
jltool head 20 data.jsonl
cat data.jsonl.gz | jltool tail 5
jltool select id,user.name,ts events.jsonl

# keep records matching a safe predicate (no eval): ==,!=,<,<=,>,>=,
# exists, contains, and/or/not, parens, dotted paths
jltool filter 'status == "error" and retries > 3' logs.jsonl
jltool filter 'user.name contains "bot" or not active' events.jsonl

# per-field presence %, null %, observed types, numeric min/max/mean/stddev,
# string cardinality (nested keys shown as dotted paths)
jltool stats data.jsonl

# infer a JSON Schema (draft 2020-12) over a full pass
jltool schema data.jsonl > schema.json

# report malformed lines (and, with --schema, non-conforming records) by
# 1-indexed line number; exits non-zero on any failure — CI-friendly
jltool validate data.jsonl
jltool validate --schema schema.json data.jsonl
```

`--limit N` stops after N input records; every command reads stdin or a file
arg and handles `.gz` transparently.

## Development

```
python -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## License

MIT
