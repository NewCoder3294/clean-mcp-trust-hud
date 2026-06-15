# Trust-HUD Glanceable Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Claude Code statusline's row 3 a glanceable, always-honest trust gauge that follows you across repos and names hallucinated calls instead of showing a wall of bars.

**Architecture:** Pure display/state changes. Add a per-repo score store (`~/.clean/scoring/<project_id>.json`) so a Swift edit can't blank or clobber a Python repo's last good score. Rewrite row 3 as a 7-state machine that leads with one colored verdict (`● REVIEW 71 · check 2 calls: a, b`) and falls back to honest one-liners. The 5-metric breakdown stays in `clean-hud`. No scoring-engine changes — flagged symbols are already persisted.

**Tech Stack:** Python 3.10–3.13, pytest (`pythonpath=["src"]`), stdlib only (json, sqlite3, os, re). Run tests with `.venv/bin/pytest`.

---

## File Structure

- `src/clean/scoring/state.py` — **modify.** Add a per-repo store: `_repo_state_path`, `write_repo_score`, `read_repo_score`. Keeps the existing global `scoring.json` writer as the "most recent event" marker.
- `src/clean/scoring/statusline.py` — **modify (bulk of work).** Add `_select_reason`, `_lang_from_path`, `_project_indexed`, `build_clean_row`; rewrite `render` and `main` for follow-me anchoring.
- `src/clean/scoring/hook.py` — **modify.** Route good scores to the per-repo store at the two write sites.
- `src/clean/scoring/daemon.py` — **modify.** Same, at its one write site.
- `src/clean/scoring/dashboard.py` — **modify.** `clean-hud` reads the per-repo good score for its launch dir so it stays meaningful after a skipped edit.
- `tests/unit/scoring/test_state.py` — **modify.** Per-repo store tests.
- `tests/unit/scoring/test_statusline.py` — **modify.** New state-machine + reason-selection tests; update old row-3 assertions.

State-flow recap:
- Global `~/.clean/scoring.json` = most recent event (any file, incl. skipped). Already written everywhere; unchanged.
- Per-repo `~/.clean/scoring/<project_id>.json` = last **non-skipped** score for that repo. New.
- The statusline resolves cwd → `project_id`, reads that repo's good score, and uses the global marker only to detect "you just touched an unsupported file in *this* repo."

---

## Task 1: Per-repo score store (state.py)

**Files:**
- Modify: `src/clean/scoring/state.py`
- Test: `tests/unit/scoring/test_state.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/scoring/test_state.py` (it already imports `FileScore`, `IndicatorResult`, `Offender` and defines `_sample_score()`):

```python
from clean.scoring.state import read_repo_score, write_repo_score


def _skipped_score() -> FileScore:
    return FileScore(
        project_id="proj",
        file_path="/tmp/proj/View.swift",
        overall_score=100,
        overall_label="OK",
        indicators=[],
        entity_count=0,
        stale=False,
        skipped=True,
    )


def test_write_repo_score_round_trips_by_project_id(tmp_path):
    write_repo_score(_sample_score(), base=tmp_path, updated_at="2026-06-06T00:00:00")
    data = read_repo_score("proj", base=tmp_path)
    assert data is not None
    assert data["overall_score"] == 82
    assert data["indicators"][0]["offenders"][0]["name"] == "frobnicate"


def test_skipped_score_is_not_persisted(tmp_path):
    write_repo_score(_skipped_score(), base=tmp_path)
    assert read_repo_score("proj", base=tmp_path) is None


def test_skipped_score_does_not_overwrite_last_good(tmp_path):
    write_repo_score(_sample_score(), base=tmp_path)
    write_repo_score(_skipped_score(), base=tmp_path)  # must be a no-op
    data = read_repo_score("proj", base=tmp_path)
    assert data is not None and data["overall_score"] == 82


def test_read_missing_repo_returns_none(tmp_path):
    assert read_repo_score("nope", base=tmp_path) is None


def test_empty_project_id_is_ignored(tmp_path):
    score = _sample_score()
    score.project_id = ""
    write_repo_score(score, base=tmp_path)
    assert read_repo_score("", base=tmp_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scoring/test_state.py -v`
Expected: FAIL with `ImportError: cannot import name 'read_repo_score'`.

- [ ] **Step 3: Implement the per-repo store**

Add to `src/clean/scoring/state.py` (after the existing imports add `import os` and `import re` if not present; `json` is already imported):

```python
PER_REPO_DIR = Path.home() / ".clean" / "scoring"


def _repo_state_path(project_id: str, base: Path = PER_REPO_DIR) -> Path:
    """Filesystem-safe per-repo state path. project_ids are already dash-safe,
    but sanitize defensively so an exotic id can never escape ``base``."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", project_id) or "_"
    return base / f"{safe}.json"


def write_repo_score(
    score: FileScore, base: Path = PER_REPO_DIR, updated_at: str | None = None
) -> None:
    """Persist the last *good* (non-skipped) score for a repo, keyed by project_id.

    Skipped scores (unsupported language, no entities) are ignored so they can
    never clobber a repo's last good number. Best-effort; never raises.
    """
    if score.skipped or not score.project_id:
        return
    try:
        base.mkdir(parents=True, exist_ok=True)
        with open(_repo_state_path(score.project_id, base), "w") as fh:
            json.dump(file_score_to_dict(score, updated_at), fh, indent=2)
    except Exception:
        pass


def read_repo_score(project_id: str, base: Path = PER_REPO_DIR) -> dict | None:
    """Read a repo's last good score, or None if absent/unreadable."""
    if not project_id:
        return None
    path = _repo_state_path(project_id, base)
    try:
        if not path.exists():
            return None
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scoring/test_state.py -v`
Expected: PASS (all, including the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/state.py tests/unit/scoring/test_state.py
git commit -m "feat(hud): per-repo score store keyed by project_id"
```

---

## Task 2: Reason selector (statusline.py)

Builds the `· …` suffix for row 3: grounding offenders win; otherwise the weakest displayed metric maps to a plain phrase.

**Files:**
- Modify: `src/clean/scoring/statusline.py`
- Test: `tests/unit/scoring/test_statusline.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/scoring/test_statusline.py`:

```python
from clean.scoring.statusline import _select_reason


def _ind(key, score, offenders=()):
    return {"key": key, "label": key, "score": score, "skipped": False,
            "offenders": [{"name": n, "detail": "", "line": 1} for n in offenders]}


def test_reason_review_names_grounding_calls():
    state = {"overall_score": 71, "indicators": [_ind("grounding", 50, ["load_index", "warm_model"])]}
    assert _select_reason(state) == " · check 2 calls: load_index, warm_model"


def test_reason_risk_says_likely_hallucinated():
    state = {"overall_score": 38, "indicators": [_ind("grounding", 20, ["foo"])]}
    assert _select_reason(state) == " · likely hallucinated: foo"


def test_reason_caps_symbol_list_at_two():
    state = {"overall_score": 50, "indicators": [_ind("grounding", 30, ["a", "b", "c", "d"])]}
    assert _select_reason(state) == " · check 4 calls: a, b +2"


def test_reason_falls_back_to_weakest_metric_phrase():
    state = {"overall_score": 72, "indicators": [
        _ind("grounding", 100), _ind("orphan", 40), _ind("alignment", 90)]}
    assert _select_reason(state) == " · low reuse"


def test_reason_empty_when_all_metrics_healthy():
    state = {"overall_score": 96, "indicators": [_ind("grounding", 100), _ind("orphan", 90)]}
    assert _select_reason(state) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -k reason -v`
Expected: FAIL with `ImportError: cannot import name '_select_reason'`.

- [ ] **Step 3: Implement `_select_reason`**

Add to `src/clean/scoring/statusline.py` (near the other render helpers; `_METRIC_PHRASE` is new):

```python
_METRIC_PHRASE = {
    "blast_radius": "high blast radius",
    "orphan": "low reuse",
    "alignment": "off-pattern",
    "duplication": "near-duplicate",
}


def _select_reason(state: dict) -> str:
    """The ` · …` suffix for row 3. Grounding offenders win; else the weakest
    displayed metric as a plain phrase; else empty when everything is healthy."""
    by_key = {i["key"]: i for i in state.get("indicators", [])}
    g = by_key.get("grounding")
    if g and g.get("offenders"):
        names = [o["name"] for o in g["offenders"]]
        shown = ", ".join(names[:2])
        extra = f" +{len(names) - 2}" if len(names) > 2 else ""
        if int(state.get("overall_score", 100)) < 60:
            return f" · likely hallucinated: {shown}{extra}"
        n = len(names)
        return f" · check {n} call{'s' if n != 1 else ''}: {shown}{extra}"
    candidates = [
        (int(i["score"]), i["key"])
        for i in state.get("indicators", [])
        if i["key"] in _METRIC_PHRASE and not i.get("skipped")
    ]
    if candidates:
        worst_score, worst_key = min(candidates)
        if worst_score < 85:
            return f" · {_METRIC_PHRASE[worst_key]}"
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -k reason -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/statusline.py tests/unit/scoring/test_statusline.py
git commit -m "feat(hud): row-3 reason selector (grounding offenders > weak metric)"
```

---

## Task 3: Row-3 state machine + helpers (statusline.py)

`build_clean_row` resolves the 7 states and renders Variant 3, using `_lang_from_path` and `_project_indexed`.

**Files:**
- Modify: `src/clean/scoring/statusline.py`
- Test: `tests/unit/scoring/test_statusline.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/scoring/test_statusline.py`:

```python
import clean.scoring.statusline as sl
from clean.scoring.statusline import GitContext, build_clean_row, _lang_from_path


def _good(score=71, label="REVIEW", offenders=("load_index", "warm_model")):
    return {"overall_score": score, "overall_label": label, "skipped": False,
            "project_id": "proj",
            "indicators": [_ind("grounding", 50, list(offenders))]}


GIT = GitContext("o/repo", "main", "proj")


def test_lang_from_path_known_and_unknown():
    assert _lang_from_path("/x/View.swift") == "Swift"
    assert _lang_from_path("/x/mod.py") == "Python"
    assert _lang_from_path("/x/data.zzz") == "ZZZ"
    assert _lang_from_path(None) is None


def test_clean_row_ok_is_calm(monkeypatch):
    row = build_clean_row(_good(96, "OK", ()), None, GIT, color=False)
    assert row == "● OK 96"


def test_clean_row_review_names_calls():
    row = build_clean_row(_good(71, "REVIEW"), None, GIT, color=False)
    assert row == "● REVIEW 71 · check 2 calls: load_index, warm_model"


def test_clean_row_risk_wording():
    row = build_clean_row(_good(38, "RISK", ("foo",)), None, GIT, color=False)
    assert row == "● RISK 38 · likely hallucinated: foo"


def test_clean_row_last_good_when_current_file_skipped():
    recent = {"skipped": True, "project_id": "proj", "file_path": "/x/View.swift"}
    row = build_clean_row(_good(71, "REVIEW", ()), recent, GIT, color=False)
    assert row == "○ 71 REVIEW · last good · Swift not scored"


def test_clean_row_not_a_repo_is_empty():
    assert build_clean_row(None, None, GitContext(None, None, None), color=False) == ""


def test_clean_row_indexed_but_unscored(monkeypatch):
    monkeypatch.setattr(sl, "_project_indexed", lambda pid: True)
    assert build_clean_row(None, None, GIT, color=False) == "clean · edit a Py/JS/TS file to score"


def test_clean_row_not_indexed(monkeypatch):
    monkeypatch.setattr(sl, "_project_indexed", lambda pid: False)
    row = build_clean_row(None, None, GitContext("o/repo", "main", "proj"), color=False)
    assert row == "clean · not indexed — index o/repo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -k "clean_row or lang_from_path" -v`
Expected: FAIL with `ImportError: cannot import name 'build_clean_row'`.

- [ ] **Step 3: Implement the helpers and state machine**

Add `import sqlite3` to the top of `src/clean/scoring/statusline.py`, then add:

```python
_LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".swift": "Swift",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".java": "Java",
    ".c": "C", ".cpp": "C++", ".cs": "C#", ".kt": "Kotlin",
}


def _lang_from_path(path: str | None) -> str | None:
    """Human language name from a file extension (best-effort)."""
    if not path:
        return None
    _, ext = os.path.splitext(path)
    if not ext:
        return None
    return _LANG_BY_EXT.get(ext.lower()) or ext.lstrip(".").upper()


def _project_indexed(project_id: str) -> bool:
    """True if the index metadata has a row for this project_id. Cheap, best-effort."""
    if not project_id:
        return False
    db = os.getenv("CLEAN_DB_PATH") or os.path.join(
        os.path.expanduser("~"), ".clean", "metadata.db"
    )
    try:
        con = sqlite3.connect(db)
        try:
            row = con.execute(
                "select 1 from projects where project_id=? limit 1", (project_id,)
            ).fetchone()
        finally:
            con.close()
        return row is not None
    except Exception:
        return False


def build_clean_row(
    repo_state: dict | None, recent: dict | None, git: GitContext | None, color: bool
) -> str:
    """Resolve and render row 3 (the clean-mcp layer) for the *current* repo."""
    if git is None or not (git.repo or git.branch):
        return ""  # not a git repo -> drop row 3

    if repo_state is not None and not repo_state.get("skipped"):
        score = int(repo_state.get("overall_score", 100))
        label = repo_state.get("overall_label", "OK")
        just_skipped_here = bool(
            recent
            and recent.get("skipped")
            and recent.get("project_id")
            and recent.get("project_id") == git.project_id
        )
        if just_skipped_here:
            lang = _lang_from_path(recent.get("file_path"))
            note = f" · {lang} not scored" if lang else ""
            dot = _paint("○", _DIM, color)
            body = _paint(f"{score} {label} · last good{note}", _DIM, color)
            return f"{dot} {body}"
        c = _color(score)
        dot = _paint("●", c + _BOLD, color)
        verdict = _paint(f"{label} {score}", c + _BOLD, color)
        reason = _select_reason(repo_state)
        return f"{dot} {verdict}{_paint(reason, _DIM, color)}"

    if repo_state is not None or _project_indexed(git.project_id):
        return _paint("clean · edit a Py/JS/TS file to score", _DIM, color)
    repo = git.repo or git.project_id or "this repo"
    return _paint(f"clean · not indexed — index {repo}", _DIM, color)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -k "clean_row or lang_from_path" -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/statusline.py tests/unit/scoring/test_statusline.py
git commit -m "feat(hud): Variant 3 row-3 state machine (follow-me, never-dark)"
```

---

## Task 4: Follow-me anchoring in render + main (statusline.py)

Rewire `render` to use `build_clean_row`, and `main` to anchor on cwd (not the last-scored file) and load the per-repo good score. Update the old row-3 tests to the new format.

**Files:**
- Modify: `src/clean/scoring/statusline.py:321-374` (`render`), `:408-424` (`main`)
- Test: `tests/unit/scoring/test_statusline.py`

- [ ] **Step 1: Update the old render tests to the new contract**

In `tests/unit/scoring/test_statusline.py`, the existing `render(...)` row-3 tests assert the old bar format. Replace these specific tests' bodies (keep the rest of the file):

```python
def test_render_layers_system_git_clean(monkeypatch):
    monkeypatch.setattr(sl, "_project_indexed", lambda pid: True)
    git = GitContext("cleanmcp/clean-mcp", "feat/trust-hud", "proj")
    out = render(_good(71, "REVIEW"), None, git, None, color=False)
    rows = out.split("\n")
    assert "cleanmcp/clean-mcp" in rows[0] and "feat/trust-hud" in rows[0]
    assert rows[1].startswith("● REVIEW 71")


def test_render_mismatched_repo_shows_repo_status(monkeypatch):
    # A good score for a *different* repo must not be shown for this repo.
    monkeypatch.setattr(sl, "_project_indexed", lambda pid: True)
    git = GitContext("o/other", "main", "other")
    out = render(None, None, git, None, color=False)
    assert "● " not in out
    assert "edit a Py/JS/TS file to score" in out


def test_render_not_a_repo_drops_clean_row():
    out = render(None, None, GitContext(None, None, None), None, color=False)
    assert out == ""
```

Delete the now-obsolete tests that assert bar/`Real calls`/`no recent score`/`82/100` behavior: `test_render_uses_plain_english_labels_and_score`, `test_index_trust_is_not_shown_as_a_bar`, `test_render_is_two_lines_with_metrics`, `test_layers_git_on_row1_clean_mcp_on_row2`, `test_render_git_context_shows_repo_and_branch`, `test_render_mismatched_repo_hides_scores`, `test_render_not_indexed_is_neutral_hint`, `test_render_stale_prefix`. (The `_select_reason`/`build_clean_row` tests now cover row 3.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -k render -v`
Expected: FAIL — `render` still has its old signature/behavior.

- [ ] **Step 3: Rewrite `render` and `main`**

Replace `render` (currently `src/clean/scoring/statusline.py:321-374`) with:

```python
def render(
    repo_state: dict | None,
    recent: dict | None = None,
    git: GitContext | None = None,
    system: SystemContext | None = None,
    color: bool = True,
) -> str:
    """Assemble the stacked HUD: row 1 system, row 2 git, row 3 clean-mcp.

    ``repo_state`` is the current repo's last good score (or None). ``recent`` is
    the most-recent-event marker, used only to flag a just-skipped file. Empty
    rows are dropped.
    """
    rows = []
    if system is not None and (
        system.model or system.ctx_used is not None or system.task
    ):
        rows.append(_system_line(system, color))
    if git is not None and (git.repo or git.branch):
        rows.append(_git_line(git, color))
    clean_row = build_clean_row(repo_state, recent, git, color)
    if clean_row:
        rows.append(clean_row)
    return "\n".join(r for r in rows if r)
```

Replace `main` (currently `:408-424`) with:

```python
def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "legend":
        print(legend())
        return
    payload = _read_payload()
    cwd = _cwd_from_payload(payload)
    git = git_context(cwd)  # follow me: anchor to where you are, not what you scored
    repo_state = read_repo_score(git.project_id) if git.project_id else None
    recent = ScoringStateWriter().read()
    system = system_context(payload)
    line = render(repo_state, recent, git, system, color=_use_color())
    if line:
        print(line)
```

Add `read_repo_score` to the existing state import at `src/clean/scoring/statusline.py:37`:

```python
from .state import ScoringStateWriter, read_repo_score
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Manual smoke test**

Run:
```bash
.venv/bin/clean-score src/clean/scoring/service.py >/dev/null
echo '{"model":{"display_name":"Opus 4.8"},"context_window":{"remaining_percentage":93,"total_tokens":1000000},"workspace":{"current_dir":"'"$PWD"'"},"session_id":"demo"}' | .venv/bin/clean-statusline
```
Expected: 3 rows; row 3 begins with `●` and a verdict like `REVIEW 71 · …` (not a wall of bars).

- [ ] **Step 6: Commit**

```bash
git add src/clean/scoring/statusline.py tests/unit/scoring/test_statusline.py
git commit -m "feat(hud): anchor statusline to cwd and render Variant 3 row 3"
```

---

## Task 5: Route good scores to the per-repo store (hook.py, daemon.py)

Every place that writes the global state must also persist the per-repo good score.

**Files:**
- Modify: `src/clean/scoring/hook.py:30-37` and `:64-70`
- Modify: `src/clean/scoring/daemon.py:35-54`
- Test: `tests/unit/scoring/test_state.py`

- [ ] **Step 1: Write the failing test (write sites call the store)**

Add to `tests/unit/scoring/test_state.py`:

```python
def test_hook_inline_persists_per_repo(tmp_path, monkeypatch):
    import clean.scoring.hook as hook
    import clean.scoring.state as state

    monkeypatch.setattr(state, "PER_REPO_DIR", tmp_path)
    captured = {}
    monkeypatch.setattr(hook, "write_repo_score", lambda s, **k: captured.setdefault("score", s))

    class _Scoring:
        def score_file(self, *a, **k):
            return _sample_score()

    class _Container:
        scoring = _Scoring()

    monkeypatch.setattr(hook, "ServiceContainer", lambda: _Container(), raising=False)
    monkeypatch.setattr(hook.ScoringStateWriter, "write", lambda self, s, **k: None, raising=False)
    hook._score_inline("/tmp/proj/mod.py", "/tmp/proj")
    assert captured["score"].project_id == "proj"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_state.py::test_hook_inline_persists_per_repo -v`
Expected: FAIL — `hook` has no `write_repo_score` / it is not called.

- [ ] **Step 3: Add per-repo writes at each site**

In `src/clean/scoring/hook.py`, change the import inside `_score_inline` (currently `from .state import ScoringStateWriter`) to:

```python
    from .state import ScoringStateWriter, write_repo_score
```

and after `ScoringStateWriter().write(score)` (line ~37) add:

```python
    write_repo_score(score)
```

In the bare-path branch of `main` (`src/clean/scoring/hook.py:66-70`), change the import to also bring in `write_repo_score` and add `write_repo_score(score)` right after `ScoringStateWriter().write(score)`.

In `src/clean/scoring/daemon.py`, change the import at line 21 to:

```python
from .state import ScoringStateWriter, file_score_to_dict, write_repo_score
```

and after `writer.write(score)` (line 53) add:

```python
    write_repo_score(score)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scoring/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/hook.py src/clean/scoring/daemon.py tests/unit/scoring/test_state.py
git commit -m "feat(hud): persist per-repo good score at all write sites"
```

---

## Task 6: clean-hud reads the per-repo good score (dashboard.py)

The full-screen dashboard reads the global `scoring.json`, which is now the most-recent event (possibly a skipped Swift edit). Point it at the per-repo good score for its launch dir so it stays meaningful.

**Files:**
- Modify: `src/clean/scoring/dashboard.py:161-196`
- Test: `tests/unit/scoring/test_dashboard.py` (create if absent)

- [ ] **Step 1: Inspect the current frame source**

Run: `.venv/bin/python -c "import inspect, clean.scoring.dashboard as d; print(inspect.getsource(d._frame))"`
Expected: shows `_frame(writer, color, scroll)` calling `writer.read()`. Confirm the read call to replace.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/scoring/test_dashboard.py`:

```python
"""clean-hud reads the per-repo good score for its launch directory."""

import clean.scoring.dashboard as dash


def test_frame_prefers_per_repo_good_score(monkeypatch, tmp_path):
    monkeypatch.setattr(dash, "_launch_project_id", lambda: "proj")
    monkeypatch.setattr(dash, "read_repo_score", lambda pid: {
        "overall_score": 71, "overall_label": "REVIEW", "skipped": False,
        "project_id": "proj", "stale": False, "indexed": True,
        "indicators": [{"key": "grounding", "label": "Grounding",
                        "score": 50, "skipped": False, "offenders": []}],
    })
    out = dash._frame(dash.ScoringStateWriter(tmp_path), color=False)
    assert "71" in out and "REVIEW" in out
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_dashboard.py -v`
Expected: FAIL — `_launch_project_id` / `read_repo_score` not present in `dashboard`.

- [ ] **Step 4: Wire the per-repo read into `_frame`**

In `src/clean/scoring/dashboard.py`, add imports near the top:

```python
import os

from .state import ScoringStateWriter, read_repo_score
from .statusline import git_context
```

Add a helper:

```python
def _launch_project_id() -> str | None:
    """project_id for the directory clean-hud was launched in."""
    return git_context(os.getcwd()).project_id
```

In `_frame(writer, color, scroll=0)`, replace the `state = writer.read()` line with a per-repo-first lookup that falls back to the global marker:

```python
    pid = _launch_project_id()
    state = (read_repo_score(pid) if pid else None) or writer.read() or {}
```

(Leave the rest of `_frame`'s rendering of the 5-metric breakdown unchanged — that's where the full detail intentionally lives.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_dashboard.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite + lint**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: all green; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/clean/scoring/dashboard.py tests/unit/scoring/test_dashboard.py
git commit -m "feat(hud): clean-hud follows the per-repo good score"
```

---

## Final verification

- [ ] Run `make test` and `make lint`; both pass.
- [ ] Manual: in this repo, edit a Python file via Claude Code and confirm row 3 shows `● <LABEL> <score> · …`. Then `git checkout` an unrelated dir / open a non-Py file and confirm row 3 degrades to `○ … last good …` or `clean · …`, never a blank where a score should be, and the repo label tracks cwd.
- [ ] Confirm `clean-hud` still renders the full 5-metric breakdown.

## Notes / known limitations (acceptable for v1)

- The `○ … Swift not scored` annotation only appears when the scorer recorded a non-empty `project_id` for the skipped file. If a skipped file is written with an empty `project_id`, row 3 still shows the repo's live last-good verdict (honest, never dark) — just without the language note. Tightening this is a scorer change, out of scope for this display project.
- **Staleness moves to `clean-hud`.** The old row 3 drew a `● stale` prefix; Variant 3 drops it from the always-on strip to keep the gauge calm. Index freshness still shows in the `clean-hud` detail view (it renders the full state, including `stale`). If you later decide you want a stale hint back on the statusline, it's a one-line marker in `build_clean_row` — out of scope for this pass.
- The old `_overall_chunk` / `_metrics_line` helpers in `statusline.py` are left in place (harmless if unused) rather than deleted, to avoid touching anything `dashboard.py` may still import.
