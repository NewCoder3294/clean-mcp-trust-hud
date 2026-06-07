"""Dependency-free syntax highlighting for the explorer preview.

Tokenizes a single line of Python/JS/TS into comment / string / number /
keyword / default spans and paints them with the statusline ANSI palette.
With color=False it returns the line unchanged.
"""

from __future__ import annotations

import os
import re

from .statusline import _BLUE, _BOLD, _CYAN, _DIM, _GREEN, _paint

_EXT_LANG = {
    ".py": "python",
    ".js": "js",
    ".jsx": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".mjs": "js",
    ".cjs": "js",
}

_KEYWORDS = {
    "python": {
        "def",
        "class",
        "return",
        "if",
        "elif",
        "else",
        "for",
        "while",
        "try",
        "except",
        "finally",
        "with",
        "as",
        "import",
        "from",
        "raise",
        "yield",
        "lambda",
        "pass",
        "break",
        "continue",
        "and",
        "or",
        "not",
        "in",
        "is",
        "None",
        "True",
        "False",
        "async",
        "await",
        "global",
        "nonlocal",
    },
    "js": {
        "function",
        "return",
        "if",
        "else",
        "for",
        "while",
        "try",
        "catch",
        "finally",
        "const",
        "let",
        "var",
        "class",
        "extends",
        "new",
        "import",
        "from",
        "export",
        "default",
        "await",
        "async",
        "yield",
        "typeof",
        "null",
        "undefined",
        "true",
        "false",
        "this",
        "super",
    },
}
_KEYWORDS["ts"] = _KEYWORDS["js"] | {
    "interface",
    "type",
    "enum",
    "implements",
    "public",
    "private",
    "protected",
    "readonly",
    "namespace",
    "declare",
    "as",
    "keyof",
}

# comment | string | number | identifier  (order matters: comments/strings first)
_TOKEN_RE = re.compile(
    r"(?P<comment>#[^\n]*|//[^\n]*)"
    r"|(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<ident>[A-Za-z_]\w*)"
)


def language_for(path: str) -> str | None:
    _, ext = os.path.splitext(path)
    return _EXT_LANG.get(ext.lower())


def highlight_line(line: str, lang: str | None, color: bool) -> str:
    if not color or lang not in _KEYWORDS:
        return line
    keywords = _KEYWORDS[lang]

    def _sub(m: re.Match) -> str:
        if m.lastgroup == "comment":
            return _paint(m.group(), _DIM, True)
        if m.lastgroup == "string":
            return _paint(m.group(), _GREEN, True)
        if m.lastgroup == "number":
            return _paint(m.group(), _CYAN, True)
        text = m.group()
        if text in keywords:
            return _paint(text, _BLUE + _BOLD, True)
        return text

    return _TOKEN_RE.sub(_sub, line)
