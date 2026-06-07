"""Tests for the dep-free syntax highlighter."""

from clean.scoring import highlight
from clean.scoring.statusline import _BLUE, _BOLD, _CYAN, _DIM, _GREEN


def test_language_for_known_extensions():
    assert highlight.language_for("a/b/x.py") == "python"
    assert highlight.language_for("x.ts") == "ts"
    assert highlight.language_for("x.tsx") == "ts"
    assert highlight.language_for("x.js") == "js"
    assert highlight.language_for("x.md") is None


def test_plain_mode_is_passthrough():
    line = "def foo():  # hi"
    assert highlight.highlight_line(line, "python", color=False) == line


def test_keyword_and_comment_get_ansi_when_colored():
    out = highlight.highlight_line("def foo():  # hi", "python", color=True)
    assert "\033[" in out  # some ANSI emitted
    assert "def" in out and "foo" in out  # text preserved
    # a comment-only line is fully dimmed
    c = highlight.highlight_line("# just a comment", "python", color=True)
    assert c.startswith("\033[2m")  # _DIM


def test_unknown_language_is_passthrough():
    assert highlight.highlight_line("anything", None, color=True) == "anything"


def test_comment_containing_keyword_stays_dim():
    out = highlight.highlight_line("a = b  # def return", "python", color=True)
    comment_part = out[out.index("#") :]
    assert _BLUE not in comment_part  # keywords inside a comment are not colored


def test_string_containing_hash_is_not_a_comment():
    out = highlight.highlight_line('s = "a # b"', "python", color=True)
    assert _GREEN in out  # the string is colored
    assert _DIM not in out  # the '#' did not start a comment


def test_keyword_is_blue_bold():
    out = highlight.highlight_line("def foo():", "python", color=True)
    assert _BLUE + _BOLD + "def" in out


def test_number_is_cyan():
    out = highlight.highlight_line("x = 42", "python", color=True)
    assert _CYAN + "42" in out


def test_identifier_with_keyword_substring_not_colored():
    out = highlight.highlight_line("return_value = 1", "python", color=True)
    assert _BLUE + _BOLD + "return_value" not in out
    assert "return_value" in out


def test_mjs_cjs_extensions():
    assert highlight.language_for("x.mjs") == "js"
    assert highlight.language_for("x.cjs") == "js"


def test_empty_line_passthrough():
    assert highlight.highlight_line("", "python", color=True) == ""
