# Self-Healing Fix Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the HUD detects a high-confidence hallucinated symbol, queue a ready-to-apply fix (the nearest real symbol from the index) in a per-repo inbox you review with a `clean-fixes` CLI — fully decoupled from your coding session, no LLM.

**Architecture:** One new module `src/clean/scoring/fixes.py` holds the whole fix-inbox lifecycle: a pure `difflib` suggester, a per-repo JSON store (mirroring the Project 1 score store), a `propose_fixes` writer wired in at the existing score-write sites, a safe `apply_fix`, and the `clean-fixes` CLI. The statusline appends a passive `· N fix ready` suffix. Zero new dependencies — `difflib`/`re`/`hashlib`/`json` are stdlib; candidate names come from the existing `store.get_by_name_substring`.

**Tech Stack:** Python 3.10–3.13, pytest (`pythonpath=["src"]`), stdlib only. Run tests with `.venv/bin/pytest`.

---

## File Structure

- `src/clean/scoring/fixes.py` — **new.** The entire fix-inbox concern: `FixSuggestion`, `suggest_candidates` (pure), `read_fixes`/`write_fixes`/`_inbox_path`/`_fix_id`, `_candidate_names` + `propose_fixes`, `apply_fix`, and `main` (the `clean-fixes` CLI).
- `src/clean/scoring/hook.py` — **modify.** Call `propose_fixes(score, container.store)` after `write_repo_score(score)` at both write sites.
- `src/clean/scoring/daemon.py` — **modify.** Same, after `write_repo_score(score)` in the handler (the container/store is available there).
- `src/clean/scoring/statusline.py` — **modify.** `build_clean_row` appends `· N fix(es) ready` from `read_fixes`.
- `pyproject.toml` — **modify.** Register `clean-fixes` console script.
- `tests/unit/scoring/test_fixes.py` — **new.** suggest / inbox I/O / propose gating / safe-apply / CLI.
- `tests/unit/scoring/test_statusline.py` — **modify.** Fix-count suffix test.

Reference types (from `src/clean/scoring/base.py`, already exist): `FileScore(project_id, file_path, overall_score, overall_label, indicators, entity_count, stale, indexed, skipped)`; `IndicatorResult(key, label, score, summary, offenders, weight, skipped, confidence)`; `Offender(name, detail, line)`. The store method used: `store.get_by_name_substring(project_id, pattern, limit) -> list[CodeEntity]` where each entity has `.name`.

---

## Task 1: Pure suggestion engine (`suggest_candidates`)

**Files:**
- Create: `src/clean/scoring/fixes.py`
- Test: `tests/unit/scoring/test_fixes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/scoring/test_fixes.py`:

```python
"""Tests for the self-healing fix inbox."""

from clean.scoring.fixes import suggest_candidates


def test_suggests_near_miss_real_symbol():
    names = ["load_repo_index", "warm_model", "save_state"]
    assert suggest_candidates("load_index", names) == ["load_repo_index"]


def test_no_candidates_below_cutoff():
    names = ["completely_different", "unrelated_thing"]
    assert suggest_candidates("load_index", names) == []


def test_matches_on_final_segment_of_dotted_symbol():
    # bad "self._procss" should match indexed method "Worker._process" via segment.
    names = ["Worker._process", "Worker._run"]
    assert suggest_candidates("self._procss", names) == ["_process"]


def test_returns_at_most_three_sorted_by_similarity():
    names = ["load_index_a", "load_index_b", "load_index_c", "load_index_d"]
    out = suggest_candidates("load_index", names, n=3)
    assert len(out) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clean.scoring.fixes'`.

- [ ] **Step 3: Create the module with the pure suggester**

Create `src/clean/scoring/fixes.py`:

```python
"""Self-healing fix inbox.

Detects a high-confidence hallucinated symbol (via the grounding indicator),
finds the nearest real symbol in the index with stdlib ``difflib`` (no model,
no API), and queues a ready-to-apply fix in a per-repo inbox the user reviews
with the ``clean-fixes`` CLI. Fully decoupled from the user's coding session.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable


def suggest_candidates(
    bad_symbol: str, names: Iterable[str], n: int = 3, cutoff: float = 0.6
) -> list[str]:
    """Up to *n* real symbol names closest to *bad_symbol* (final segment).

    Matching is done on the final dotted segment (so ``self._procss`` matches an
    indexed ``Worker._process`` and yields ``_process``). Below *cutoff* nothing
    is returned — a low-similarity guess is worse than silence.
    """
    seg = bad_symbol.split(".")[-1]
    segs = sorted({nm.split(".")[-1] for nm in names if nm})
    return difflib.get_close_matches(seg, segs, n=n, cutoff=cutoff)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/fixes.py tests/unit/scoring/test_fixes.py
git commit -m "feat(fixes): difflib symbol suggester (no model)"
```

---

## Task 2: Per-repo fix inbox store

**Files:**
- Modify: `src/clean/scoring/fixes.py`
- Test: `tests/unit/scoring/test_fixes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/scoring/test_fixes.py`:

```python
from clean.scoring.fixes import FixSuggestion, _fix_id, read_fixes, write_fixes


def _entry(file_path="/p/mod.py", bad="load_index", cands=("load_repo_index",)):
    return {
        "id": _fix_id(file_path, bad), "file_path": file_path, "line": 42,
        "bad_symbol": bad, "candidates": list(cands), "created_at": "2026-06-14T00:00:00",
    }


def test_write_then_read_round_trips(tmp_path):
    write_fixes("proj", [_entry()], base=tmp_path)
    got = read_fixes("proj", base=tmp_path)
    assert len(got) == 1 and got[0]["bad_symbol"] == "load_index"


def test_read_missing_returns_empty_list(tmp_path):
    assert read_fixes("nope", base=tmp_path) == []


def test_empty_project_id_is_ignored(tmp_path):
    write_fixes("", [_entry()], base=tmp_path)
    assert read_fixes("", base=tmp_path) == []


def test_fix_id_is_stable_for_same_file_and_symbol():
    assert _fix_id("/p/mod.py", "load_index") == _fix_id("/p/mod.py", "load_index")
    assert _fix_id("/p/mod.py", "load_index") != _fix_id("/p/mod.py", "warm_model")


def test_fixsuggestion_dataclass_fields():
    s = FixSuggestion(id="x", file_path="/p/m.py", line=1, bad_symbol="b",
                      candidates=["c"], created_at="t")
    assert s.bad_symbol == "b" and s.candidates == ["c"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -k "round_trips or missing_returns or empty_project or fix_id or dataclass" -v`
Expected: FAIL with `ImportError: cannot import name 'FixSuggestion'`.

- [ ] **Step 3: Add the model + store**

Add to `src/clean/scoring/fixes.py` (extend the imports at the top to include `hashlib`, `json`, `re`, `dataclass`, `Path`):

```python
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

FIX_INBOX_DIR = Path.home() / ".clean" / "fixes"


@dataclass
class FixSuggestion:
    """One queued fix: swap a hallucinated symbol for a real one."""

    id: str
    file_path: str
    line: int | None
    bad_symbol: str
    candidates: list[str]
    created_at: str


def _fix_id(file_path: str, bad_symbol: str) -> str:
    """Stable short id so the same hallucination is not queued twice."""
    return hashlib.sha1(f"{file_path}::{bad_symbol}".encode()).hexdigest()[:8]


def _inbox_path(project_id: str, base: Path = FIX_INBOX_DIR) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", project_id) or "_"
    return base / f"{safe}.json"


def read_fixes(project_id: str, base: Path = FIX_INBOX_DIR) -> list[dict]:
    """Pending fixes for a repo, or [] if absent/unreadable."""
    if not project_id:
        return []
    path = _inbox_path(project_id, base)
    try:
        if not path.exists():
            return []
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_fixes(project_id: str, entries: list[dict], base: Path = FIX_INBOX_DIR) -> None:
    """Replace a repo's inbox. Best-effort; never raises."""
    if not project_id:
        return
    try:
        base.mkdir(parents=True, exist_ok=True)
        with open(_inbox_path(project_id, base), "w") as fh:
            json.dump(entries, fh, indent=2)
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -v`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/fixes.py tests/unit/scoring/test_fixes.py
git commit -m "feat(fixes): per-repo fix inbox store"
```

---

## Task 3: `propose_fixes` (trigger gating + queue/prune)

**Files:**
- Modify: `src/clean/scoring/fixes.py`
- Test: `tests/unit/scoring/test_fixes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/scoring/test_fixes.py`:

```python
from clean.scoring.base import FileScore, IndicatorResult, Offender
from clean.scoring.fixes import propose_fixes


class _FakeEntity:
    def __init__(self, name):
        self.name = name


class _FakeStore:
    """Returns names containing the queried token (mimics get_by_name_substring)."""

    def __init__(self, names):
        self._names = names

    def get_by_name_substring(self, project_id, pattern, limit=20):
        p = pattern.lower()
        return [_FakeEntity(n) for n in self._names if p in n.lower()][:limit]


def _score(offenders=(Offender("load_index", "no match", 42),), confidence=1.0,
           skipped=False, indexed=True, project_id="proj"):
    return FileScore(
        project_id=project_id, file_path="/p/mod.py", overall_score=40,
        overall_label="RISK",
        indicators=[IndicatorResult("grounding", "Grounding", 40, "1 unresolved",
                                    offenders=tuple(offenders), confidence=confidence)],
        entity_count=3, stale=False, indexed=indexed, skipped=skipped)


def test_propose_queues_a_fix_for_high_confidence_hallucination(tmp_path):
    store = _FakeStore(["load_repo_index", "warm_model"])
    propose_fixes(_score(), store, base=tmp_path)
    fixes = read_fixes("proj", base=tmp_path)
    assert len(fixes) == 1
    assert fixes[0]["bad_symbol"] == "load_index"
    assert fixes[0]["candidates"] == ["load_repo_index"]


def test_no_fix_when_index_stale(tmp_path):
    store = _FakeStore(["load_repo_index"])
    propose_fixes(_score(confidence=0.7), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_no_fix_when_skipped_or_unindexed(tmp_path):
    store = _FakeStore(["load_repo_index"])
    propose_fixes(_score(skipped=True), store, base=tmp_path)
    propose_fixes(_score(indexed=False), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_no_fix_when_no_near_match(tmp_path):
    store = _FakeStore(["totally_unrelated"])
    propose_fixes(_score(), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_reproposing_same_file_prunes_resolved_offenders(tmp_path):
    store = _FakeStore(["load_repo_index", "warm_model_fn"])
    propose_fixes(_score(), store, base=tmp_path)  # queues load_index
    # Re-score: the hallucination is gone, a different one appears.
    propose_fixes(_score(offenders=(Offender("warm_model", "no match", 9),)),
                  store, base=tmp_path)
    fixes = read_fixes("proj", base=tmp_path)
    assert len(fixes) == 1 and fixes[0]["bad_symbol"] == "warm_model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -k propose -v`
Expected: FAIL with `ImportError: cannot import name 'propose_fixes'`.

- [ ] **Step 3: Implement `_candidate_names` + `propose_fixes`**

Add to `src/clean/scoring/fixes.py` (extend imports with `from datetime import datetime`):

```python
def _candidate_names(store, project_id: str, bad_symbol: str, per_token_limit: int = 100) -> list[str]:
    """Indexed names sharing a >=3-char token with the bad symbol's final segment."""
    seg = bad_symbol.split(".")[-1]
    tokens = [t for t in re.split(r"[._]|(?<=[a-z])(?=[A-Z])", seg) if len(t) >= 3] or [seg]
    names: list[str] = []
    for tok in tokens:
        try:
            names.extend(e.name for e in store.get_by_name_substring(project_id, tok, limit=per_token_limit))
        except Exception:
            continue
    return names


def propose_fixes(score, store, base: Path = FIX_INBOX_DIR) -> None:
    """Queue fixes for high-confidence hallucinated symbols. Best-effort; never raises.

    Trigger: the score is real (not skipped, project indexed) and the grounding
    indicator is fresh (confidence == 1.0) with offenders. For each offender with
    a near-match real symbol, write an inbox entry. Re-running for a file replaces
    that file's entries, so resolved hallucinations are pruned.
    """
    try:
        if score.skipped or not score.indexed or not score.project_id:
            return
        grounding = next((i for i in score.indicators if i.key == "grounding"), None)
        if grounding is None or grounding.confidence < 1.0 or not grounding.offenders:
            return
        new_entries: list[dict] = []
        for off in grounding.offenders:
            cands = suggest_candidates(off.name, _candidate_names(store, score.project_id, off.name))
            if not cands:
                continue
            seg = off.name.split(".")[-1]
            new_entries.append(
                {
                    "id": _fix_id(score.file_path, seg),
                    "file_path": score.file_path,
                    "line": off.line,
                    "bad_symbol": seg,
                    "candidates": cands,
                    "created_at": datetime.now().isoformat(),
                }
            )
        kept = [e for e in read_fixes(score.project_id, base) if e.get("file_path") != score.file_path]
        write_fixes(score.project_id, kept + new_entries, base)
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/fixes.py tests/unit/scoring/test_fixes.py
git commit -m "feat(fixes): propose_fixes trigger gating + queue/prune"
```

---

## Task 4: Safe `apply_fix`

**Files:**
- Modify: `src/clean/scoring/fixes.py`
- Test: `tests/unit/scoring/test_fixes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/scoring/test_fixes.py`:

```python
from clean.scoring.fixes import apply_fix


def _file_entry(path, bad="load_index", cands=("load_repo_index",)):
    return {"id": "x", "file_path": str(path), "line": 2, "bad_symbol": bad,
            "candidates": list(cands), "created_at": "t"}


def test_apply_replaces_unique_occurrence(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def f():\n    return load_index()\n")
    assert apply_fix(_file_entry(f)) == "applied"
    assert f.read_text() == "def f():\n    return load_repo_index()\n"


def test_apply_is_stale_when_symbol_absent(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def f():\n    return other()\n")
    assert apply_fix(_file_entry(f)) == "stale"
    assert "other()" in f.read_text()  # untouched


def test_apply_is_stale_when_ambiguous(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("load_index()\nload_index()\n")  # two occurrences -> never guess
    assert apply_fix(_file_entry(f)) == "stale"
    assert f.read_text() == "load_index()\nload_index()\n"


def test_apply_does_not_touch_substring_matches(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("x = load_index\ny = load_index_helper\n")  # whole-word only
    assert apply_fix(_file_entry(f)) == "applied"
    assert f.read_text() == "x = load_repo_index\ny = load_index_helper\n"


def test_apply_pick_selects_candidate(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("load_index()\n")
    assert apply_fix(_file_entry(f, cands=("a_fn", "load_repo_index")), pick=1) == "applied"
    assert f.read_text() == "load_repo_index()\n"


def test_apply_bad_pick_returns_error(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("load_index()\n")
    assert apply_fix(_file_entry(f), pick=5) == "error"


def test_apply_missing_file_is_stale(tmp_path):
    assert apply_fix(_file_entry(tmp_path / "nope.py")) == "stale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -k apply -v`
Expected: FAIL with `ImportError: cannot import name 'apply_fix'`.

- [ ] **Step 3: Implement `apply_fix`**

Add to `src/clean/scoring/fixes.py`:

```python
def apply_fix(entry: dict, pick: int = 0) -> str:
    """Apply a queued fix. Returns 'applied', 'stale', or 'error'.

    Safe contract: replace the bad symbol only if it occurs **exactly once** in
    the file as a whole identifier token. Zero or multiple occurrences -> 'stale'
    (never guess which one). The file is left untouched unless exactly one match.
    """
    candidates = entry.get("candidates") or []
    if not isinstance(pick, int) or pick < 0 or pick >= len(candidates):
        return "error"
    replacement = candidates[pick]
    bad = entry.get("bad_symbol") or ""
    path = entry.get("file_path") or ""
    if not bad:
        return "error"
    try:
        with open(path) as fh:
            src = fh.read()
    except OSError:
        return "stale"
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(bad)}(?![A-Za-z0-9_])")
    if len(pattern.findall(src)) != 1:
        return "stale"
    try:
        with open(path, "w") as fh:
            fh.write(pattern.sub(replacement, src, count=1))
    except OSError:
        return "error"
    return "applied"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/fixes.py tests/unit/scoring/test_fixes.py
git commit -m "feat(fixes): safe apply_fix (unique-occurrence whole-word replace)"
```

---

## Task 5: `clean-fixes` CLI

**Files:**
- Modify: `src/clean/scoring/fixes.py`, `pyproject.toml`
- Test: `tests/unit/scoring/test_fixes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/scoring/test_fixes.py`:

```python
import clean.scoring.fixes as fixes_mod


def test_cli_lists_pending_fixes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    write_fixes("proj", [_entry()], base=tmp_path)
    monkeypatch.setattr("sys.argv", ["clean-fixes"])
    fixes_mod.main()
    out = capsys.readouterr().out
    assert "load_index" in out and "load_repo_index" in out


def test_cli_apply_removes_entry_on_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    f = tmp_path / "mod.py"
    f.write_text("load_index()\n")
    entry = {"id": "abc123", "file_path": str(f), "line": 1, "bad_symbol": "load_index",
             "candidates": ["load_repo_index"], "created_at": "t"}
    write_fixes("proj", [entry], base=tmp_path)
    monkeypatch.setattr("sys.argv", ["clean-fixes", "apply", "abc123"])
    fixes_mod.main()
    assert "applied" in capsys.readouterr().out.lower()
    assert read_fixes("proj", base=tmp_path) == []
    assert f.read_text() == "load_repo_index()\n"


def test_cli_reject_removes_entry(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    entry = {"id": "abc123", "file_path": "/p/m.py", "line": 1, "bad_symbol": "x",
             "candidates": ["y"], "created_at": "t"}
    write_fixes("proj", [entry], base=tmp_path)
    monkeypatch.setattr("sys.argv", ["clean-fixes", "reject", "abc123"])
    fixes_mod.main()
    assert read_fixes("proj", base=tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -k cli -v`
Expected: FAIL with `AttributeError: module 'clean.scoring.fixes' has no attribute 'main'` (or `_current_project_id`).

- [ ] **Step 3: Implement the CLI**

Add to `src/clean/scoring/fixes.py` (extend imports with `import os` and `import sys`):

```python
def _current_project_id() -> str | None:
    """project_id for the directory clean-fixes was run in."""
    from .statusline import git_context

    return git_context(os.getcwd()).project_id


def _print_list(entries: list[dict]) -> None:
    if not entries:
        print("No pending fixes.")
        return
    for e in entries:
        cands = e.get("candidates") or []
        best = cands[0] if cands else "?"
        more = f"  (+{len(cands) - 1} more)" if len(cands) > 1 else ""
        loc = f"{os.path.basename(e.get('file_path', '?'))}:{e.get('line', '?')}"
        print(f"[{e.get('id')}] {loc}  {e.get('bad_symbol')} → {best}{more}")


def main() -> None:
    argv = sys.argv[1:]
    pid = _current_project_id()
    entries = read_fixes(pid) if pid else []

    if not argv:
        _print_list(entries)
        return

    cmd = argv[0]
    if cmd not in ("apply", "reject") or len(argv) < 2:
        print("usage: clean-fixes [apply <id> [--pick N] | reject <id>]")
        return

    fix_id = argv[1]
    match = next((e for e in entries if e.get("id") == fix_id), None)
    if match is None:
        print(f"No pending fix with id {fix_id}.")
        return

    if cmd == "reject":
        write_fixes(pid, [e for e in entries if e.get("id") != fix_id])
        print(f"Rejected {fix_id}.")
        return

    pick = 0
    if "--pick" in argv:
        try:
            pick = int(argv[argv.index("--pick") + 1])
        except (ValueError, IndexError):
            pick = 0
    result = apply_fix(match, pick=pick)
    if result == "applied":
        write_fixes(pid, [e for e in entries if e.get("id") != fix_id])
        print(f"Applied {fix_id}: {match.get('bad_symbol')} → {match['candidates'][pick]}")
    elif result == "stale":
        write_fixes(pid, [e for e in entries if e.get("id") != fix_id])
        print(f"Skipped {fix_id} (stale: the symbol is gone or appears more than once).")
    else:
        print(f"Could not apply {fix_id} (bad --pick index).")
```

- [ ] **Step 4: Register the console script**

In `pyproject.toml`, under `[project.scripts]`, add the line after `clean-ide`:

```toml
clean-fixes = "clean.scoring.fixes:main"
```

Then reinstall the entry point: `.venv/bin/pip install -e ".[dev]" -q`

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add src/clean/scoring/fixes.py tests/unit/scoring/test_fixes.py pyproject.toml
git commit -m "feat(fixes): clean-fixes CLI (list/apply/reject)"
```

---

## Task 6: Wire `propose_fixes` into the score-write sites

**Files:**
- Modify: `src/clean/scoring/hook.py`, `src/clean/scoring/daemon.py`
- Test: `tests/unit/scoring/test_fixes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/scoring/test_fixes.py`. These are behavioral — they verify `propose_fixes` is actually invoked with the score and the container's store at each site:

```python
def test_hook_inline_calls_propose_fixes(monkeypatch):
    import clean.scoring.hook as hook

    captured = {}
    monkeypatch.setattr(hook, "propose_fixes", lambda score, store, **k: captured.setdefault("args", (score, store)))
    monkeypatch.setattr(hook, "write_repo_score", lambda s, **k: None)
    monkeypatch.setattr(hook.ScoringStateWriter, "write", lambda self, s, **k: None, raising=False)

    sc = _score()  # the FileScore factory defined earlier in this file

    class _Store:
        pass

    class _Scoring:
        def score_file(self, *a, **k):
            return sc

    class _Container:
        store = _Store()
        scoring = _Scoring()

    c = _Container()
    monkeypatch.setattr(hook, "ServiceContainer", lambda: c, raising=False)
    hook._score_inline("/p/mod.py", "/p")
    assert captured["args"][0] is sc
    assert captured["args"][1] is c.store


def test_daemon_handler_calls_propose_fixes(monkeypatch):
    import clean.scoring.daemon as daemon

    captured = {}
    monkeypatch.setattr(daemon, "propose_fixes", lambda score, store, **k: captured.setdefault("args", (score, store)))
    monkeypatch.setattr(daemon, "write_repo_score", lambda s, **k: None)

    sc = _score()

    class _Store:
        def count(self, pid):
            return 0  # skip the incremental reindex branch

    class _Scoring:
        def score_file(self, *a, **k):
            return sc

    class _Container:
        store = _Store()
        scoring = _Scoring()

    class _Writer:
        def write(self, s, **k):
            pass

    c = _Container()
    daemon._handle_request({"file_path": "/p/mod.py"}, c, _Writer())
    assert captured["args"][0] is sc
    assert captured["args"][1] is c.store
```

(`_score()` is the `FileScore` factory added in Task 3's test block; these tests live in the same file so it's in scope.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -k "calls_propose_fixes" -v`
Expected: FAIL with `AttributeError` — `propose_fixes` not imported in those modules yet.

- [ ] **Step 3: Wire the call sites**

In `src/clean/scoring/hook.py`: add `propose_fixes` to the top-level fixes/state imports — change the existing `from .state import ScoringStateWriter, write_repo_score` region to also import fixes:

```python
from .fixes import propose_fixes
```

In `_score_inline` (which already builds `container = ServiceContainer()` and calls `write_repo_score(score)`), add right after `write_repo_score(score)`:

```python
    propose_fixes(score, container.store)
```

In `main`'s bare-path branch (which builds `container = ServiceContainer()` and writes the score), add after `write_repo_score(score)`:

```python
    propose_fixes(score, container.store)
```

In `src/clean/scoring/daemon.py`: add `from .fixes import propose_fixes` at the top (next to the existing `from .state import ScoringStateWriter, file_score_to_dict, write_repo_score`). `_handle_request(payload, container, writer)` already takes `container` as a parameter and uses `container.store` (line 47/52) and `writer.write(score)` then `write_repo_score(score)` (lines 53-54). Add immediately after `write_repo_score(score)`:

```python
    propose_fixes(score, container.store)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_fixes.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + lint**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: green; ruff clean (watch for unused imports).

- [ ] **Step 6: Commit**

```bash
git add src/clean/scoring/hook.py src/clean/scoring/daemon.py tests/unit/scoring/test_fixes.py
git commit -m "feat(fixes): propose fixes at all score-write sites"
```

---

## Task 7: HUD fix-count suffix

**Files:**
- Modify: `src/clean/scoring/statusline.py`
- Test: `tests/unit/scoring/test_statusline.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/scoring/test_statusline.py`:

```python
def test_clean_row_appends_fix_count(monkeypatch):
    monkeypatch.setattr(sl, "read_fixes", lambda pid: [{"id": "a"}])
    row = build_clean_row(_good(38, "RISK", ("load_index",)), None, GIT, color=False)
    assert row.endswith("· 1 fix ready")


def test_clean_row_pluralizes_fix_count(monkeypatch):
    monkeypatch.setattr(sl, "read_fixes", lambda pid: [{"id": "a"}, {"id": "b"}])
    row = build_clean_row(_good(38, "RISK", ("load_index",)), None, GIT, color=False)
    assert row.endswith("· 2 fixes ready")


def test_clean_row_no_fix_suffix_when_none(monkeypatch):
    monkeypatch.setattr(sl, "read_fixes", lambda pid: [])
    row = build_clean_row(_good(96, "OK", ()), None, GIT, color=False)
    assert "fix ready" not in row and "fixes ready" not in row
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -k fix -v`
Expected: FAIL — `sl` has no `read_fixes` / suffix not appended.

- [ ] **Step 3: Append the fix-count suffix**

In `src/clean/scoring/statusline.py`, add the import near the state import:

```python
from .fixes import read_fixes
```

In `build_clean_row`, in the **live verdict branch** (the one returning `● {label} {score}{reason}`), compute and append the fix suffix. Replace the return:

```python
        c = _color(score)
        dot = _paint("●", c + _BOLD, color)
        verdict = _paint(f"{label} {score}", c + _BOLD, color)
        reason = _select_reason(repo_state)
        fixes = read_fixes(git.project_id) if git.project_id else []
        fix_suffix = ""
        if fixes:
            n = len(fixes)
            fix_suffix = f" · {n} fix{'es' if n != 1 else ''} ready"
        return f"{dot} {verdict}{_paint(reason, _DIM, color)}{_paint(fix_suffix, _DIM, color)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scoring/test_statusline.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + lint + manual smoke**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/ruff check src tests
```
Expected: all green; ruff clean.

Manual end-to-end (optional, proves the loop): in a Python file in this repo, introduce a near-miss hallucinated call (e.g. call `load_repo_indx` where `load_repo_index` exists), let the score hook run, then:
```bash
.venv/bin/clean-score <that_file> >/dev/null
.venv/bin/clean-fixes
```
Expected: the inbox lists `… load_repo_indx → load_repo_index`. `clean-fixes apply <id>` rewrites it; `clean-fixes` then shows "No pending fixes."

- [ ] **Step 6: Commit**

```bash
git add src/clean/scoring/statusline.py tests/unit/scoring/test_statusline.py
git commit -m "feat(fixes): HUD shows pending fix count"
```

---

## Self-review notes

- The fix module is built incrementally (Tasks 1-5) but stays one cohesive concern (the inbox lifecycle). If `fixes.py` exceeds ~300 lines, that's acceptable here — it has one responsibility.
- `propose_fixes` and `apply_fix` are best-effort and never raise into the hook/daemon hot paths (same discipline as `write_repo_score`).
- Known v1 limits (documented in the spec): run-together symbols sharing no ≥3-char token may yield no candidate; method/dotted offenders are matched/replaced on their final segment; the fix-count suffix shows only in the live-verdict HUD branch (where a hallucination reason already appears).
