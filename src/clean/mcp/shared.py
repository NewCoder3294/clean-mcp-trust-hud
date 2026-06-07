"""Shared MCP helper functions used by both cloud and local MCP servers.

These are pure utility functions with no tool-handler logic.
"""

from __future__ import annotations

from ..core.models import CodeEntity, SearchContext, SearchResult


# ---------------------------------------------------------------------------
# Path relativization helpers
# ---------------------------------------------------------------------------


def _relativize_results(
    results: list[SearchResult], root_path: str
) -> list[SearchResult]:
    """Strip the server-side root prefix from file paths in search results.

    Args:
        results: Raw search results with absolute file paths.
        root_path: Absolute path of the cloned repository root.

    Returns:
        New list of :class:`SearchResult` with relative file paths.
    """
    prefix = root_path.rstrip("/") + "/"
    out: list[SearchResult] = []
    for sr in results:
        fp = sr.entity.file_path
        if fp.startswith(prefix):
            fp = fp[len(prefix) :]
        out.append(
            SearchResult(entity=sr.entity.with_file_path(fp), similarity=sr.similarity)
        )
    return out


def _relativize_context(
    context: SearchContext | None, root_path: str
) -> SearchContext | None:
    """Strip the server-side root prefix from paths in the expanded context.

    Args:
        context: Expanded call-graph context, or ``None``.
        root_path: Absolute path of the cloned repository root.

    Returns:
        A new :class:`SearchContext` with relative paths, or ``None``.
    """
    if context is None:
        return None
    prefix = root_path.rstrip("/") + "/"

    def _rel(e: CodeEntity) -> CodeEntity:
        fp = e.file_path
        return e.with_file_path(fp[len(prefix) :]) if fp.startswith(prefix) else e

    return SearchContext(
        function=_rel(context.function) if context.function else None,
        callees=[_rel(e) for e in context.callees],
        callers=[_rel(e) for e in context.callers],
        same_file=[_rel(e) for e in context.same_file],
    )


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------


def _validate_repo_format(repo: str) -> str | None:
    """Return an error message when *repo* is not in ``owner/repo`` format.

    Args:
        repo: Repository identifier supplied by the MCP caller.

    Returns:
        A human-readable error string, or ``None`` when the format is valid.
    """
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return (
            f"Invalid repo format: '{repo}'. "
            "Expected 'owner/repo' (e.g. 'facebook/react')."
        )
    owner, name = parts
    if ".." in owner or ".." in name:
        return (
            f"Invalid repo format: '{repo}'. "
            "Owner and repo names must not contain '..' components."
        )
    if len(owner) > 39:
        return f"Invalid repo format: owner '{owner}' exceeds the 39-character limit."
    if len(name) > 100:
        return (
            f"Invalid repo format: repo name '{name}' exceeds the 100-character limit."
        )
    from ..repo.manager import _is_ssrf_name

    if _is_ssrf_name(owner) or _is_ssrf_name(name):
        return (
            f"Invalid repo format: '{repo}'. "
            "Owner and repo names must not be IP addresses or internal hostnames."
        )
    return None


def _resolve_single_repo(
    metadata,
    org_id: str | None = None,
    branch: str | None = None,
) -> tuple[str, str | None] | str:
    """Auto-select repo when only one is indexed.

    Args:
        metadata: :class:`MetadataStore` instance.
        org_id: Optional organisation ID to scope the lookup.
        branch: Optional branch filter.

    Returns:
        ``(repo, branch)`` tuple when exactly one ready repo is found.
        An error string when zero or multiple repos are found.
    """
    projects = metadata.list_projects(org_id=org_id)
    ready = [p for p in projects if p.status == "ready"]
    if branch is not None:
        branch_ready = [p for p in ready if p.branch == branch]
        if branch_ready:
            ready = branch_ready
    if len(ready) == 1:
        resolved_branch = branch if branch is not None else ready[0].branch
        return (ready[0].repo_full_name, resolved_branch)
    if len(ready) == 0:
        return "No repositories indexed. Run index_repo first."
    names = ", ".join(
        f"'{p.repo_full_name}'" + (f"@{p.branch}" if p.branch else "") for p in ready
    )
    return (
        f"Multiple repos indexed: {names}. "
        "Specify which one with the 'repo' parameter "
        "(and 'branch' if needed)."
    )


def _make_project_id(repo: str, branch: str | None = None) -> str:
    """Build a collision-safe project ID from *repo* and optional *branch*.

    Args:
        repo: Repository in ``owner/repo`` format.
        branch: Optional git branch name.

    Returns:
        A lower-cased, slash-free string suitable for use as a LanceDB table
        name or SQLite primary key.

    Uses ``--`` as the owner/repo separator so that hyphens and underscores
    in owner or repo names remain distinct (``owner_repo`` vs ``owner--repo``).
    """
    # Fix Issue 11: use "--" separator so "foo/bar-baz" != "foo/bar_baz"
    base = repo.replace("/", "--").lower()
    if branch:
        safe_branch = branch.replace("/", "_").lower()
        return f"{base}--{safe_branch}"
    return base


# ---------------------------------------------------------------------------
# Local git / project-id detection
# ---------------------------------------------------------------------------


def _detect_git_repo(cwd: str) -> str | None:
    """Return 'owner/repo' by parsing the git origin remote URL, or None."""
    import re
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # handles both https://github.com/owner/repo.git and git@github.com:owner/repo.git
            m = re.search(r"[:/]([a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+?)(?:\.git)?$", url)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def _detect_git_branch(cwd: str) -> str | None:
    """Return the current git branch name for the repo at *cwd*, or None."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            # "HEAD" means detached — not useful
            return branch if branch and branch != "HEAD" else None
    except Exception:
        pass
    return None


def resolve_local_project_id(path: str, branch: str | None = None) -> str:
    """Derive the project ID for a local folder exactly as ``index_repo`` does.

    This is the single source of truth shared by the local-path indexer
    (``_handle_index_local_path``) and the Trust-HUD scoring layer, so the two
    can never drift: a folder indexed under one ID must be looked up under the
    same ID.

    Resolution mirrors the indexer:

    1. If *path* is a git repo with a GitHub ``origin`` remote, use
       ``owner/repo``.
    2. Otherwise use the sanitized folder basename, prefixed ``local/`` to
       avoid clashes with real GitHub repos.

    The branch (passed in or detected from the working tree) is folded into the
    ID via :func:`_make_project_id`.
    """
    import os
    import re

    abs_path = os.path.abspath(os.path.expanduser(path))

    repo_full_name = _detect_git_repo(abs_path)
    if not repo_full_name:
        folder = os.path.basename(abs_path.rstrip(os.sep)) or "root"
        folder = re.sub(r"[^a-zA-Z0-9._-]", "-", folder).lower() or "local"
        repo_full_name = f"local/{folder}"

    branch = (branch or "").strip() or _detect_git_branch(abs_path) or None
    return _make_project_id(repo_full_name, branch)
