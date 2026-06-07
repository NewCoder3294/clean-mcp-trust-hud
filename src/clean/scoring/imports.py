"""Extract the names a file imports, for import-aware grounding.

Imports are resolved at score-time from the edited file's own source — no index
or schema change needed. A bare call to an imported name (``defaultdict()`` from
``from collections import defaultdict``, ``useState()`` from ``import {useState}
from 'react'``) must NOT be flagged as a hallucination.

Regex-based on purpose: tree-sitter import-node shapes vary across grammar
versions, and a parse miss here would reintroduce false positives. Regex fails
safe — a missed import name degrades to today's behavior, never worse.
"""

from __future__ import annotations

import re

from ..core.types import Language

_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+(.+)$", re.M)
_PY_FROM = re.compile(r"^[ \t]*from[ \t]+[.\w]+[ \t]+import[ \t]+(.+)$", re.M)

_JS_NS = re.compile(r"import\s+\*\s+as\s+(\w+)")
_JS_DEFAULT = re.compile(r"import\s+(\w+)\s*(?:,|from\b)")
_JS_NAMED = re.compile(r"import\s+(?:type\s+)?(?:\w+\s*,\s*)?\{([^}]*)\}")
_JS_REQUIRE_DEFAULT = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*require\s*\(")
_JS_REQUIRE_NAMED = re.compile(r"(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\s*\(")


def _clean(name: str) -> str:
    return name.replace("type ", "").strip()


def _from_named_clause(clause: str, names: set[str]) -> None:
    for part in clause.split(","):
        part = _clean(part)
        if not part:
            continue
        # `a as b` (JS) / `a: b` (require destructure) -> bound name is the alias
        if " as " in part:
            names.add(part.split(" as ")[-1].strip())
        elif ":" in part:
            names.add(part.split(":")[-1].strip())
        else:
            names.add(part)


def extract_imported_names(
    language: Language, source: bytes
) -> tuple[frozenset[str], bool]:
    """Return (imported_names, has_wildcard) bound into the file's scope.

    ``has_wildcard`` is True for Python ``from x import *`` — callers should
    then treat any bare name as possibly-imported (suppress flagging).
    """
    try:
        text = source.decode("utf-8", errors="replace")
    except Exception:
        return frozenset(), False

    names: set[str] = set()
    wildcard = False

    if language == Language.PYTHON:
        for m in _PY_IMPORT.finditer(text):
            for part in m.group(1).split(","):
                part = part.strip()
                if not part:
                    continue
                if " as " in part:
                    names.add(part.split(" as ")[-1].strip())
                else:  # `import a.b.c` binds the top module `a`
                    names.add(part.split(".")[0].strip())
        for m in _PY_FROM.finditer(text):
            rhs = m.group(1).strip()
            if rhs.startswith("*"):
                wildcard = True
                continue
            rhs = rhs.strip("()").strip()
            for part in rhs.split(","):
                part = part.strip().strip("()").strip()
                if not part:
                    continue
                if " as " in part:
                    names.add(part.split(" as ")[-1].strip())
                else:
                    names.add(part.split(".")[-1].strip())
    else:  # JavaScript / TypeScript
        for m in _JS_NS.finditer(text):
            names.add(m.group(1))
        for m in _JS_DEFAULT.finditer(text):
            if m.group(1) != "type":
                names.add(m.group(1))
        for m in _JS_NAMED.finditer(text):
            _from_named_clause(m.group(1), names)
        for m in _JS_REQUIRE_DEFAULT.finditer(text):
            names.add(m.group(1))
        for m in _JS_REQUIRE_NAMED.finditer(text):
            _from_named_clause(m.group(1), names)

    names.discard("")
    names.discard("type")
    return frozenset(names), wildcard
