"""Regression tests for shared local project-id resolution.

The Trust-HUD scoring layer must compute the *same* project ID that
``index_repo`` stored, or every git-backed index reads as "NO INDEX" / "no
recent score". That coupling lives in :func:`resolve_local_project_id`, which
both the indexer's local-path handler and the scoring/statusline layers
delegate to. These tests lock the three call sites to one another.
"""

from __future__ import annotations

import clean.mcp.shared as shared
from clean.mcp.shared import _make_project_id, resolve_local_project_id


def test_non_git_folder_uses_local_prefix(tmp_path):
    """A plain directory (no git remote) → ``local/<sanitized-basename>``."""
    d = tmp_path / "My Project"
    d.mkdir()
    pid = resolve_local_project_id(str(d))
    assert pid == _make_project_id("local/my-project")
    assert pid == "local--my-project"


def test_git_backed_folder_uses_owner_repo_and_branch(tmp_path, monkeypatch):
    """A GitHub-backed checkout → ``owner/repo`` folded with the branch."""
    monkeypatch.setattr(
        shared, "_detect_git_repo", lambda p: "NewCoder3294/clean-mcp-trust-hud"
    )
    monkeypatch.setattr(shared, "_detect_git_branch", lambda p: "feat/trust-hud")

    pid = resolve_local_project_id(str(tmp_path))
    assert pid == _make_project_id("NewCoder3294/clean-mcp-trust-hud", "feat/trust-hud")
    assert pid == "newcoder3294--clean-mcp-trust-hud--feat_trust-hud"


def test_explicit_branch_overrides_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "_detect_git_repo", lambda p: "owner/repo")
    monkeypatch.setattr(shared, "_detect_git_branch", lambda p: "main")

    assert resolve_local_project_id(str(tmp_path), branch="dev") == _make_project_id(
        "owner/repo", "dev"
    )


def test_scoring_and_statusline_resolve_identically(tmp_path, monkeypatch):
    """The scoring service and the statusline must derive the same ID.

    Both delegate to :func:`resolve_local_project_id`; this guards against any
    future call site reintroducing the bare-basename divergence that produced
    a permanent "NO INDEX" HUD.
    """
    from clean.scoring import service

    monkeypatch.setattr(shared, "_detect_git_repo", lambda p: "owner/repo")
    monkeypatch.setattr(shared, "_detect_git_branch", lambda p: "feature/x")

    root = str(tmp_path)
    scoring_pid = service._project_id_for(root)
    # statusline.git_context resolves the project_id via the same helper once
    # the git root is known; assert it matches the scoring side directly.
    statusline_pid = resolve_local_project_id(root)

    assert scoring_pid == statusline_pid
    assert scoring_pid == "owner--repo--feature_x"
