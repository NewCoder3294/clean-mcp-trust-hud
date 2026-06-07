"""Tests for import-name extraction (import-aware grounding)."""

from clean.core.types import Language
from clean.scoring.imports import extract_imported_names


def _py(src: str):
    return extract_imported_names(Language.PYTHON, src.encode())


def _js(src: str):
    return extract_imported_names(Language.JAVASCRIPT, src.encode())


def test_python_from_import():
    names, wildcard = _py("from collections import defaultdict, OrderedDict")
    assert "defaultdict" in names and "OrderedDict" in names
    assert wildcard is False


def test_python_import_as_and_dotted():
    names, _ = _py("import numpy as np\nimport os.path\n")
    assert "np" in names
    assert "os" in names  # `import os.path` binds top module `os`


def test_python_from_import_as():
    names, _ = _py("from a.b import thing as t")
    assert "t" in names and "thing" not in names


def test_python_wildcard():
    _, wildcard = _py("from mod import *")
    assert wildcard is True


def test_js_named_and_default_and_namespace():
    names, _ = _js(
        "import React, { useState, useEffect as fx } from 'react'\n"
        "import * as utils from './utils'\n"
    )
    assert {"React", "useState", "fx", "utils"} <= names


def test_ts_type_import_ignored_as_binding_noise():
    names, _ = _js("import type { Foo } from './types'\n")
    assert "Foo" in names
    assert "type" not in names


def test_js_require():
    names, _ = _js("const fs = require('fs')\nconst { join } = require('path')\n")
    assert {"fs", "join"} <= names


def test_garbage_is_safe():
    names, wildcard = _js("this is not valid code {{{")
    assert isinstance(names, frozenset)
    assert wildcard is False
