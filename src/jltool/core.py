"""Core streaming helpers for jltool.

Everything here is streaming and tolerant of malformed lines: callers decide
whether a bad line is fatal (validate) or skippable (head/select/...).
"""

from __future__ import annotations

import gzip
import io
import json
import math
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator


@dataclass
class BadLine:
    lineno: int
    raw: str
    error: str


def open_source(path: str | None) -> io.TextIOBase:
    """Open a path (gzip-aware) or stdin as a text stream."""
    if path is None or path == "-":
        return sys.stdin
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def iter_records(
    stream: Iterable[str], *, on_bad: str = "skip"
) -> Iterator[tuple[int, Any]]:
    """Yield (lineno, obj) for each non-blank line.

    on_bad: "skip" ignores unparseable lines, "raise" raises ValueError,
    "yield" yields (lineno, BadLine(...)).
    """
    for lineno, line in enumerate(stream, start=1):
        s = line.strip()
        if not s:
            continue
        try:
            yield lineno, json.loads(s)
        except json.JSONDecodeError as e:
            if on_bad == "raise":
                raise ValueError(f"line {lineno}: {e}") from e
            if on_bad == "yield":
                yield lineno, BadLine(lineno, s, str(e))
            # "skip": fall through


def get_path(obj: Any, dotted: str) -> tuple[bool, Any]:
    """Resolve a dotted path. Returns (found, value)."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def json_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


# --------------------------------------------------------------------------
# filter: a tiny safe predicate grammar (no eval)
#
#   expr    := or_expr
#   or_expr := and_expr ("or" and_expr)*
#   and_expr:= not_expr ("and" not_expr)*
#   not_expr:= "not" not_expr | atom
#   atom    := "(" expr ")" | comparison
#   comparison := PATH OP VALUE | PATH "exists" | PATH "contains" VALUE
#   OP      := == != < <= > >=
#   VALUE   := json scalar (number, "string", true, false, null) or bare word
# --------------------------------------------------------------------------

_OPS = {"==", "!=", "<", "<=", ">", ">="}


def _tokenize(expr: str) -> list[str]:
    toks: list[str] = []
    i, n = 0, len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c in "()":
            toks.append(c)
            i += 1
            continue
        if c in "\"'":
            j = i + 1
            buf = []
            while j < n and expr[j] != c:
                if expr[j] == "\\" and j + 1 < n:
                    buf.append(expr[j + 1])
                    j += 2
                    continue
                buf.append(expr[j])
                j += 1
            if j >= n:
                raise ValueError("unterminated string literal in filter expr")
            toks.append("\x00" + "".join(buf))  # sentinel-prefixed string literal
            i = j + 1
            continue
        if expr.startswith("==", i) or expr.startswith("!=", i) or \
           expr.startswith("<=", i) or expr.startswith(">=", i):
            toks.append(expr[i:i + 2])
            i += 2
            continue
        if c in "<>":
            toks.append(c)
            i += 1
            continue
        # bare word: path, number, keyword
        j = i
        while j < n and not expr[j].isspace() and expr[j] not in "()<>=!":
            j += 1
        toks.append(expr[i:j])
        i = j
    return toks


def _parse_value(tok: str) -> Any:
    if tok.startswith("\x00"):
        return tok[1:]
    low = tok.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    return tok  # bare string


class _Parser:
    def __init__(self, toks: list[str]):
        self.toks = toks
        self.pos = 0

    def peek(self) -> str | None:
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def next(self) -> str:
        if self.pos >= len(self.toks):
            raise ValueError("unexpected end of filter expression")
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def parse(self):
        node = self.parse_or()
        if self.pos != len(self.toks):
            raise ValueError(f"trailing tokens in filter expr: {self.toks[self.pos:]}")
        return node

    def parse_or(self):
        left = self.parse_and()
        while (self.peek() or "").lower() == "or":
            self.next()
            right = self.parse_and()
            left = ("or", left, right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while (self.peek() or "").lower() == "and":
            self.next()
            right = self.parse_not()
            left = ("and", left, right)
        return left

    def parse_not(self):
        if (self.peek() or "").lower() == "not":
            self.next()
            return ("not", self.parse_not())
        return self.parse_atom()

    def parse_atom(self):
        t = self.peek()
        if t == "(":
            self.next()
            node = self.parse_or()
            if self.peek() != ")":
                raise ValueError("missing closing paren in filter expr")
            self.next()
            return node
        return self.parse_comparison()

    def parse_comparison(self):
        path = self.next()
        if path in ("(", ")") or path is None:
            raise ValueError("expected a field path in filter expr")
        if path.startswith("\x00"):
            raise ValueError("left side of a comparison must be a field path")
        op = self.peek()
        if op is None:
            raise ValueError(f"expected an operator after '{path}'")
        lop = op.lower()
        if lop == "exists":
            self.next()
            return ("exists", path)
        if lop == "contains":
            self.next()
            return ("contains", path, _parse_value(self.next()))
        if op in _OPS:
            self.next()
            return ("cmp", op, path, _parse_value(self.next()))
        raise ValueError(f"unexpected token '{op}' after field '{path}'")


def _cmp(op: str, a: Any, b: Any) -> bool:
    try:
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
    except TypeError:
        return False
    return False


def _eval(node, obj: Any) -> bool:
    tag = node[0]
    if tag == "or":
        return _eval(node[1], obj) or _eval(node[2], obj)
    if tag == "and":
        return _eval(node[1], obj) and _eval(node[2], obj)
    if tag == "not":
        return not _eval(node[1], obj)
    if tag == "exists":
        return get_path(obj, node[1])[0]
    if tag == "contains":
        found, val = get_path(obj, node[1])
        if not found:
            return False
        needle = node[2]
        if isinstance(val, str):
            return str(needle) in val
        if isinstance(val, (list, dict)):
            return needle in val
        return False
    if tag == "cmp":
        _, op, path, want = node
        found, val = get_path(obj, path)
        if not found:
            return False
        return _cmp(op, val, want)
    raise AssertionError(node)


def compile_filter(expr: str):
    """Return a predicate fn(obj) -> bool for a filter expression."""
    toks = _tokenize(expr)
    if not toks:
        raise ValueError("empty filter expression")
    ast = _Parser(toks).parse()
    return lambda obj: _eval(ast, obj)


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------

@dataclass
class _FieldStat:
    present: int = 0
    nulls: int = 0
    types: dict = field(default_factory=dict)
    nmin: float = math.inf
    nmax: float = -math.inf
    nsum: float = 0.0
    nsumsq: float = 0.0
    ncount: int = 0
    strings: set = field(default_factory=set)
    string_overflow: bool = False


_STRCAP = 10000


def _flatten(obj: Any, prefix: str, out: dict) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, f"{prefix}.{k}" if prefix else k, out)
    else:
        out[prefix] = obj


def collect_stats(records: Iterable[tuple[int, Any]]) -> dict:
    fields: dict[str, _FieldStat] = {}
    total = 0
    for _, obj in records:
        total += 1
        flat: dict[str, Any] = {}
        if isinstance(obj, dict):
            _flatten(obj, "", flat)
        else:
            flat[""] = obj
        for key, val in flat.items():
            fs = fields.setdefault(key, _FieldStat())
            fs.present += 1
            t = json_type(val)
            fs.types[t] = fs.types.get(t, 0) + 1
            if val is None:
                fs.nulls += 1
            elif isinstance(val, bool):
                pass
            elif isinstance(val, (int, float)):
                fs.nmin = min(fs.nmin, val)
                fs.nmax = max(fs.nmax, val)
                fs.nsum += val
                fs.nsumsq += val * val
                fs.ncount += 1
            elif isinstance(val, str):
                if not fs.string_overflow:
                    fs.strings.add(val)
                    if len(fs.strings) > _STRCAP:
                        fs.string_overflow = True
                        fs.strings = set()
    out: dict[str, Any] = {"records": total, "fields": {}}
    for key, fs in sorted(fields.items()):
        entry: dict[str, Any] = {
            "presence": round(fs.present / total, 4) if total else 0,
            "null_pct": round(fs.nulls / fs.present, 4) if fs.present else 0,
            "types": dict(sorted(fs.types.items(), key=lambda kv: -kv[1])),
        }
        if fs.ncount:
            mean = fs.nsum / fs.ncount
            var = max(fs.nsumsq / fs.ncount - mean * mean, 0.0)
            entry["numeric"] = {
                "min": fs.nmin,
                "max": fs.nmax,
                "mean": round(mean, 6),
                "stddev": round(math.sqrt(var), 6),
                "count": fs.ncount,
            }
        if fs.string_overflow:
            entry["string_cardinality"] = f">{_STRCAP}"
        elif fs.strings:
            entry["string_cardinality"] = len(fs.strings)
        out["fields"][key or "<root>"] = entry
    return out


# --------------------------------------------------------------------------
# schema inference (JSON Schema draft 2020-12, structural subset)
# --------------------------------------------------------------------------

class _SchemaNode:
    __slots__ = ("types", "props", "prop_seen", "count", "items", "required_pool")

    def __init__(self):
        self.types: set[str] = set()
        self.props: dict[str, _SchemaNode] = {}
        self.prop_seen: dict[str, int] = {}
        self.count = 0
        self.items: _SchemaNode | None = None
        self.required_pool: set[str] | None = None

    def observe(self, val: Any) -> None:
        self.count += 1
        t = json_type(val)
        self.types.add(t)
        if t == "object":
            keys = set(val.keys())
            self.required_pool = keys if self.required_pool is None else (self.required_pool & keys)
            for k, v in val.items():
                child = self.props.get(k)
                if child is None:
                    child = self.props[k] = _SchemaNode()
                self.prop_seen[k] = self.prop_seen.get(k, 0) + 1
                child.observe(v)
        elif t == "array":
            if self.items is None:
                self.items = _SchemaNode()
            for v in val:
                self.items.observe(v)

    def to_schema(self) -> dict:
        ordered = [t for t in ("object", "array", "string", "integer",
                               "number", "boolean", "null") if t in self.types]
        schema: dict[str, Any] = {}
        if len(ordered) == 1:
            schema["type"] = ordered[0]
        elif ordered:
            schema["type"] = ordered
        if "object" in self.types and self.props:
            schema["properties"] = {k: v.to_schema() for k, v in self.props.items()}
            req = sorted(self.required_pool or ())
            if req:
                schema["required"] = req
        if "array" in self.types and self.items is not None:
            schema["items"] = self.items.to_schema()
        return schema


def infer_schema(records: Iterable[tuple[int, Any]]) -> dict:
    root = _SchemaNode()
    for _, obj in records:
        root.observe(obj)
    schema = root.to_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


# --------------------------------------------------------------------------
# validate against an inferred/loaded schema (structural subset)
# --------------------------------------------------------------------------

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def schema_errors(schema: dict, value: Any, path: str = "$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = [t] if isinstance(t, str) else list(t)
        if not any(_TYPE_CHECKS.get(x, lambda v: True)(value) for x in types):
            errs.append(f"{path}: expected type {t}, got {json_type(value)}")
            return errs
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in enum")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}: missing required property '{req}'")
        props = schema.get("properties", {})
        for k, sub in props.items():
            if k in value:
                errs.extend(schema_errors(sub, value[k], f"{path}.{k}"))
    if isinstance(value, list) and "items" in schema:
        for idx, item in enumerate(value):
            errs.extend(schema_errors(schema["items"], item, f"{path}[{idx}]"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    return errs
