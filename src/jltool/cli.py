"""Command-line entry point for jltool.

Subcommands: head, tail, select, filter, stats, schema, validate.
Everything streams; nothing loads the whole file except where a full pass is
inherent (stats, schema, tail).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from typing import Sequence

from . import __version__
from .core import (
    BadLine,
    collect_stats,
    compile_filter,
    dump,
    get_path,
    infer_schema,
    iter_records,
    open_source,
    schema_errors,
)


def _limited(records, limit):
    if limit is None:
        yield from records
        return
    for i, rec in enumerate(records):
        if i >= limit:
            break
        yield rec


def _cmd_head(args: argparse.Namespace) -> int:
    with open_source(args.file) as stream:
        for i, (_, obj) in enumerate(iter_records(stream)):
            if i >= args.n:
                break
            print(dump(obj))
    return 0


def _cmd_tail(args: argparse.Namespace) -> int:
    buf: collections.deque = collections.deque(maxlen=args.n)
    with open_source(args.file) as stream:
        for _, obj in iter_records(stream):
            buf.append(obj)
    for obj in buf:
        print(dump(obj))
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    with open_source(args.file) as stream:
        for _, obj in _limited(iter_records(stream), args.limit):
            out = {}
            for f in fields:
                found, val = get_path(obj, f)
                if found:
                    out[f] = val
            print(dump(out))
    return 0


def _cmd_filter(args: argparse.Namespace) -> int:
    try:
        pred = compile_filter(args.expr)
    except ValueError as e:
        print(f"jltool filter: {e}", file=sys.stderr)
        return 2
    with open_source(args.file) as stream:
        for _, obj in _limited(
            ((ln, o) for ln, o in iter_records(stream) if pred(o)), args.limit
        ):
            print(dump(obj))
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    with open_source(args.file) as stream:
        result = collect_stats(_limited(iter_records(stream), args.limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    with open_source(args.file) as stream:
        result = infer_schema(_limited(iter_records(stream), args.limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    schema = None
    if args.schema:
        with open(args.schema, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    failures = 0
    checked = 0
    with open_source(args.file) as stream:
        for lineno, obj in _limited(
            iter_records(stream, on_bad="yield"), args.limit
        ):
            checked += 1
            if isinstance(obj, BadLine):
                failures += 1
                print(f"line {lineno}: malformed JSON: {obj.error}", file=sys.stderr)
                continue
            if schema is not None:
                errs = schema_errors(schema, obj)
                if errs:
                    failures += 1
                    for e in errs:
                        print(f"line {lineno}: {e}", file=sys.stderr)
    print(
        f"checked {checked} record(s), {failures} failure(s)",
        file=sys.stderr,
    )
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jltool", description="JSONL-native toolkit")
    p.add_argument("--version", action="version", version=f"jltool {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--limit", type=int, default=None,
                        help="stop after N input records")

    h = sub.add_parser("head", help="first N records")
    h.add_argument("n", type=int, nargs="?", default=10)
    h.add_argument("file", nargs="?")
    h.set_defaults(func=_cmd_head)

    t = sub.add_parser("tail", help="last N records")
    t.add_argument("n", type=int, nargs="?", default=10)
    t.add_argument("file", nargs="?")
    t.set_defaults(func=_cmd_tail)

    s = sub.add_parser("select", help="project fields by dotted path")
    s.add_argument("fields", help="comma-separated dotted paths")
    s.add_argument("file", nargs="?")
    add_common(s)
    s.set_defaults(func=_cmd_select)

    f = sub.add_parser("filter", help="keep records matching a safe predicate")
    f.add_argument("expr", help="e.g. 'age > 30 and country == \"US\"'")
    f.add_argument("file", nargs="?")
    add_common(f)
    f.set_defaults(func=_cmd_filter)

    st = sub.add_parser("stats", help="per-field presence / types / numeric summary")
    st.add_argument("file", nargs="?")
    add_common(st)
    st.set_defaults(func=_cmd_stats)

    sc = sub.add_parser("schema", help="infer a JSON Schema (draft 2020-12)")
    sc.add_argument("file", nargs="?")
    add_common(sc)
    sc.set_defaults(func=_cmd_schema)

    v = sub.add_parser("validate", help="report malformed / non-conforming lines")
    v.add_argument("file", nargs="?")
    v.add_argument("--schema", help="JSON Schema file to validate each record against")
    add_common(v)
    v.set_defaults(func=_cmd_validate)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
