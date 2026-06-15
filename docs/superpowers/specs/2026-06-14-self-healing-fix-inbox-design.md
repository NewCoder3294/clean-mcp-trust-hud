# Self-Healing Fix Inbox (Project 2)

- **Date:** 2026-06-14
- **Status:** Draft for review
- **Scope:** Turn the Trust-HUD from a passive gauge into a self-healer for the one
  class of problem it detects unambiguously: **hallucinated symbols**. Detect →
  suggest a real symbol → queue a ready-to-apply fix → you review and apply.
- **Repo:** `NewCoder3294/clean-mcp-trust-hud`, branch `feat/trust-hud`
- **Builds on:** Project 1 (glanceable display) — reuses the per-repo store pattern,
  the write-at-score-sites pattern, and the row-3 suffix.

## Context

The grounding indicator already detects hallucinated calls: it names the unresolved
symbol, its line, and a `confidence` (1.0 fresh index, 0.7 stale, 0.0 no index). Today
that's *displayed* and nothing more. This project closes the loop — from *detect* to
*fix* — for hallucinated symbols only, because that's the one failure class with a
crisp, automatable correction: **a hallucinated symbol is almost always a near-miss of
a real one** (`load_index` → `load_repo_index`).

## Guiding constraints (from the design conversation)

- **No LLM, no API keys, no local models.** The fix is computed with Python's stdlib
  `difflib` over the symbol names already in the index. The existing embedding model is
  **not** involved.
- **No new infrastructure.** No daemon orchestration, no detached processes, no git
  worktrees. Fix suggestion happens inline at the same points that already write the
  score (hook + daemon), exactly like `write_repo_score`.
- **Never interrupt the coding session.** The fixer is fully decoupled from the Claude
  session the user codes with. The *only* thing that ever reaches that session is a
  passive count on the HUD. Nothing auto-applies.
- **Prove value cheaply.** This is a minimal v1 to find out if it helps before investing
  in anything heavier.

## Goals

1. **Detect** (reuse): when a grounding offender exists and the index is fresh
   (`confidence == 1.0`), treat that offender as a fixable hallucination.
2. **Suggest** (new, stdlib only): find up to 3 real indexed symbols whose names are
   close to the bad symbol, via `difflib`. If none are close enough, queue nothing.
3. **Queue** (new, mirrors the score store): write suggestions to a per-repo **fix
   inbox** at the same sites that write scores.
4. **Review & apply** (new CLI `clean-fixes`): list pending fixes; apply one via an
   exact whole-symbol replace on the recorded line, or skip it as stale; reject one.
5. **Surface** (HUD): append a passive `· N fix(es) ready` to row 3 for the current repo.

## Non-Goals (explicitly deferred)

- **Structural / multi-line fixes** (anything beyond a single-symbol substitution). Those
  need a reasoning agent; that is a future **escalation tier** and, when built, must run
  as a headless/isolated agent — never the user's live session.
- **Auto-apply.** Fixes never touch the working tree without an explicit `clean-fixes
  apply`.
- **Fuzzy patching.** If the recorded line/symbol no longer matches, the fix is skipped
  as stale, never force-applied.
- Fixing anything other than grounding hallucinations (blast-radius, reuse, style, etc.
  are judgment calls, not mechanical fixes).

## Design

### 1. Trigger (precise)

A fix is proposed for a grounding offender when **all** hold:
- the score is not `skipped` and the project is `indexed`;
- the grounding indicator's `confidence == 1.0` (fresh index — never act on stale);
- the offender's symbol gets at least one `difflib` candidate above the cutoff.

This is independent of the overall verdict band — a hallucinated call is worth fixing
whether the file scored REVIEW or RISK overall.

### 2. Suggestion engine (`difflib`, no model)

For a bad symbol `b`, candidates come from the project's **indexed entity names** (the
same names the grounding indicator already resolves against, retrieved from the existing
`VectorStore` for the project):

```
candidates = difflib.get_close_matches(b, indexed_names, n=3, cutoff=0.6)
```

- `cutoff=0.6` keeps only genuine near-misses; a low-similarity guess is worse than
  silence, so an empty result queues nothing.
- For a dotted/method symbol (`self._foo`), match on the final segment (`_foo`) against
  indexed names' final segments, consistent with how grounding classifies method calls.
- The candidate population is the indexed names for the offender's `project_id`. (Exact
  retrieval method — a bulk name list vs. substring-seeded narrowing — is a planning
  detail; it must use the existing store, no new index.)

### 3. Fix inbox (per-repo store, mirrors `state.py`)

`~/.clean/fixes/<project_id>.json` — a list of entries:

```json
{
  "id": "<short stable hash of file+line+bad_symbol>",
  "file_path": "/abs/path/foo.py",
  "line": 42,
  "bad_symbol": "load_index",
  "candidates": ["load_repo_index", "load_index_meta"],
  "created_at": "<iso>"
}
```

- `id` is a stable hash so the same hallucination isn't queued twice (dedup on re-score).
- Written by a new `propose_fixes(score, store)` called at the three score-write sites
  (`hook._score_inline`, `hook.main` bare-path, `daemon._handle_request`), right after
  `write_repo_score(score)`. Best-effort, never raises (same discipline as the score
  writer). It is a no-op when the trigger conditions aren't met.
- When an offender no longer appears in a fresh score (the agent fixed it, or it was
  applied), its stale entry is pruned on the next score of that file.

This lives in a new module `src/clean/scoring/fixes.py` (single responsibility: the fix
inbox — model, suggest, store I/O, apply), separate from the indicators.

### 4. Review & apply CLI — `clean-fixes`

New console script `clean-fixes = clean.scoring.fixes:main`, operating on the current
repo (resolved via the existing `git_context(os.getcwd()).project_id`, like the HUD):

- `clean-fixes` (no args) — list pending fixes:
  `[a1b2] foo.py:42  load_index → load_repo_index  (+1 more)`
- `clean-fixes apply <id> [--pick N]` — apply the chosen candidate (default: the first).
  **Safe-apply contract:** read the file; the bad symbol must occur **exactly once** in
  the file as a whole identifier token; if so, replace that single occurrence with the
  chosen candidate and write the file; if it occurs zero times (gone/already fixed) or
  more than once (ambiguous), do **not** edit — report the entry as **stale**. No
  fuzzy matching, no guessing which occurrence. (The grounding offender records the
  enclosing function's start line, not the exact call line, so a unique whole-file
  occurrence is the reliable safe target rather than a single recorded line; `line` is
  kept for display context only.)
- `clean-fixes reject <id>` — remove the entry.

### 5. HUD surface

`build_clean_row` (statusline) appends a passive suffix when the current repo's inbox is
non-empty: `… · 1 fix ready` / `… · 3 fixes ready`. Read via `read_fixes(git.project_id)`.
This is the only footprint in the coding session — a count, never an action. The
`clean-hud` dashboard may list the pending fixes in its detail view (optional, low
priority).

## Affected files

- `src/clean/scoring/fixes.py` — **new.** Inbox model, `propose_fixes`, `read_fixes` /
  `write_fixes`, `apply_fix`, and the `clean-fixes` CLI (`main`).
- `src/clean/scoring/hook.py` — call `propose_fixes(score, store)` after
  `write_repo_score(score)` at both sites (the store/container is already constructed
  there).
- `src/clean/scoring/daemon.py` — same, after `write_repo_score(score)` in the handler.
- `src/clean/scoring/statusline.py` — `build_clean_row` appends the `· N fix(es) ready`
  suffix from `read_fixes`.
- `pyproject.toml` — register `clean-fixes` console script.
- `tests/unit/scoring/` — `test_fixes.py` (suggest, inbox I/O, safe-apply incl. the stale
  path, dedup) and a statusline test for the fix-count suffix.

## Testing

All core logic is pure functions over fixtures — no daemon, no model, no network.

- **Suggest:** `difflib` over a fixture name list returns the expected near-miss; below
  cutoff returns none; dotted/method symbol matches on the final segment.
- **Trigger gating:** no suggestion when `skipped`, not `indexed`, or grounding
  `confidence < 1.0`.
- **Inbox I/O:** write/read per-repo; dedup by `id`; prune of resolved entries.
- **Safe-apply:** symbol present on the recorded line → applied (file content changes
  exactly the one token); symbol moved/absent → reported stale, file untouched.
- **HUD suffix:** `1 fix ready` / `3 fixes ready` appears for a repo with pending fixes;
  absent when empty; correct singular/plural.

Follow the user's testing rules (deterministic, single logical assertion focus, mock the
filesystem via `tmp_path`). Keep `fail_under = 60`.

## Rollout / proving it

Ship behind no flag (it's inert until a real high-confidence hallucination occurs and a
near-match exists). If after real use it earns its keep, consider the escalation tier
(headless isolated reasoning agent for structural fixes). If it doesn't, it cost one
small module and a stdlib call to find out.

## Resolved decisions

- **Apply safety:** replace the bad symbol only when it occurs exactly once in the file
  (whole-word); zero or multiple occurrences → skip as stale. No fuzzy patching, no
  auto-apply. (Refined from "recorded line" after finding the offender line is the
  entity start, not the call line.) Decided 2026-06-14.
- **Candidate retrieval:** seed `difflib` from `store.get_by_name_substring` queries on
  the bad symbol's tokens — reuses the existing store, no new storage/protocol method.
  Known v1 limit: a run-together symbol sharing no ≥3-char token with the real name may
  yield no candidates (queues nothing rather than guessing). Decided 2026-06-14.
- **Candidates:** up to 3 near-matches (`difflib n=3, cutoff=0.6`), first is the default
  on `apply`. Decided 2026-06-14.
- **Fixer engine:** deterministic stdlib `difflib` over indexed names — no LLM, no API
  key, no model. Decided 2026-06-14.
- **Coupling:** fully decoupled from the user's Claude session; only a passive HUD count
  crosses over. Decided 2026-06-14.
