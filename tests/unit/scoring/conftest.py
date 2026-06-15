"""Put this directory on sys.path so tests can ``import helpers``."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture(autouse=True)
def _no_real_fix_inbox(monkeypatch):
    """Default the HUD's fix-count lookup to empty so statusline tests are
    hermetic. Tests that exercise the fix-count suffix re-patch
    ``read_fixes`` to a non-empty list, which overrides this default."""
    monkeypatch.setattr("clean.scoring.statusline.read_fixes", lambda pid: [], raising=False)
