"""Tests for the clean-ide launcher helpers."""

import pytest

from clean.scoring import ide


def test_sidebar_command_uses_module_invocation():
    cmd = ide._sidebar_command("/usr/bin/python3", "%4")
    assert "clean.scoring.explorer --sidebar" in cmd
    assert "CLEAN_TREE_TARGET=%4" in cmd
    assert "/usr/bin/python3" in cmd


def test_require_tmux_raises_when_missing(monkeypatch):
    monkeypatch.setattr(ide.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit):
        ide._require_tmux()


def test_require_tmux_ok_when_present(monkeypatch):
    monkeypatch.setattr(ide.shutil, "which", lambda _name: "/opt/homebrew/bin/tmux")
    ide._require_tmux()  # does not raise


def test_editor_command_wraps_in_shell():
    assert ide._editor_command("vim") == ["sh", "-c", "vim"]
    assert ide._editor_command("code --wait") == ["sh", "-c", "code --wait"]
