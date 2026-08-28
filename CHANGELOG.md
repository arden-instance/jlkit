# Changelog

All notable changes to `jltool` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — unreleased

Initial public release.

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

[0.1.0]: https://github.com/arden-instance/jltool/releases/tag/v0.1.0
