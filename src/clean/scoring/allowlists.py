"""Per-language allowlists of names that must never count as hallucinations.

These cover language builtins/globals and the most common stdlib module names.
Anything in here is treated as a legitimate external reference even though it
will not be found in the indexed codebase.
"""

from __future__ import annotations

import builtins

from ..core.types import Language

# Python: every builtin (print, len, dict, isinstance, super, ...) plus the
# top-level stdlib modules people commonly call into.
_PYTHON_BUILTINS = frozenset(dir(builtins))
_PYTHON_STDLIB = frozenset(
    {
        "os",
        "sys",
        "re",
        "json",
        "math",
        "time",
        "datetime",
        "typing",
        "dataclasses",
        "pathlib",
        "collections",
        "asyncio",
        "logging",
        "functools",
        "itertools",
        "subprocess",
        "shutil",
        "hashlib",
        "enum",
        "abc",
        "contextlib",
        "threading",
        "io",
        "copy",
        "random",
        "uuid",
        "warnings",
        "traceback",
        "inspect",
        "string",
        "struct",
        "socket",
        "base64",
        "pickle",
        "tempfile",
        "glob",
        "csv",
        "sqlite3",
        "unittest",
        "argparse",
        "operator",
        "decimal",
        "fractions",
        "statistics",
    }
)
PYTHON_ALLOWLIST = _PYTHON_BUILTINS | _PYTHON_STDLIB

# JS/TS: globals plus universally-available built-in array/promise/object
# methods so a bare ``map``/``then`` is never flagged.
JS_ALLOWLIST = frozenset(
    {
        "console",
        "Promise",
        "Array",
        "Object",
        "JSON",
        "Math",
        "Date",
        "Number",
        "String",
        "Boolean",
        "Symbol",
        "Map",
        "Set",
        "WeakMap",
        "WeakSet",
        "RegExp",
        "Error",
        "TypeError",
        "Proxy",
        "Reflect",
        "fetch",
        "setTimeout",
        "setInterval",
        "clearTimeout",
        "clearInterval",
        "require",
        "process",
        "Buffer",
        "module",
        "exports",
        "global",
        "globalThis",
        "window",
        "document",
        "navigator",
        "localStorage",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "encodeURIComponent",
        "decodeURIComponent",
        "structuredClone",
        "queueMicrotask",
        # common built-in methods (appear as bare last-segment of chains)
        "map",
        "filter",
        "reduce",
        "forEach",
        "find",
        "some",
        "every",
        "push",
        "pop",
        "shift",
        "unshift",
        "slice",
        "splice",
        "concat",
        "join",
        "then",
        "catch",
        "finally",
        "keys",
        "values",
        "entries",
        "get",
        "set",
        "has",
        "add",
        "delete",
        "toString",
        "valueOf",
    }
)

# Names that should never be flagged in any language.
UNIVERSAL_ALLOWLIST = frozenset(
    {"__init__", "__new__", "__call__", "__enter__", "__exit__", "super"}
)


def allowlist_for(language: Language) -> frozenset[str]:
    """Return the allowlist for *language* merged with the universal set."""
    if language == Language.PYTHON:
        return PYTHON_ALLOWLIST | UNIVERSAL_ALLOWLIST
    if language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
        return JS_ALLOWLIST | UNIVERSAL_ALLOWLIST
    return UNIVERSAL_ALLOWLIST


def is_allowlisted(name: str, language: Language) -> bool:
    """True if a bare name is a builtin/global and must not be flagged."""
    return name in allowlist_for(language)
