# Changelog

All notable changes to `jlkit` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-08-28

First release published to PyPI.

### Added
- `head` / `tail` accept `-n/--lines N` (GNU-style) in addition to the
  positional count.

### Fixed
- `jlkit head data.jsonl` (count omitted) no longer errors with
  "invalid int value" — a lone positional is treated as the file, not the count.
- `jlkit head <non-number> file` now exits 2 with a clear message instead of an
  argparse type error.

## [0.1.0] — 2026-08-28

Initial public release (GitHub tag only; superseded by 0.1.1 on PyPI).

### Added
- `head N` / `tail N` — first/last N records, streaming; `tail` keeps only an
  N-record ring buffer.
- `select FIELDS` — project comma-separated dotted paths (`id,user.name,ts`).
- `filter EXPR` — keep records matching a safe no-eval predicate grammar:
  `==,!=,<,<=,>,>=`, `exists`, `contains`, `and`/`or`/`not`, parentheses,
  dotted paths.
- `stats` — per-field presence %, null %, observed types, numeric
  min/max/mean/stddev, string cardinality; nested keys flattened to dotted paths.
- `schema` — infer a JSON Schema (draft 2020-12, structural subset) over a full pass.
- `validate` — report malformed lines by 1-indexed number; with `--schema`,
  also report non-conforming records. Exits non-zero on any failure (CI-friendly).
- Global `--limit N` — stop after N input records.
- Transparent `.gz` input; reads a file arg or stdin.
- Requires Python 3.12+ (argparse in 3.12 handles options interspersed with
  positional arguments, e.g. `jlkit select name --limit 1 data.jsonl`).

### Changed
- A missing or unreadable input file now prints a one-line
  `jlkit CMD: cannot open '...': <reason>` (exit 2) instead of a traceback.
- Writing to a closed pipe (`jlkit ... | head`) exits quietly instead of
  raising `BrokenPipeError` on shutdown.

[0.1.1]: https://github.com/arden-instance/jlkit/releases/tag/v0.1.1
[0.1.0]: https://github.com/arden-instance/jlkit/releases/tag/v0.1.0
