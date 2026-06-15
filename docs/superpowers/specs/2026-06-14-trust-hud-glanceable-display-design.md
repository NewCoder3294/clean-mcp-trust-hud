# Trust-HUD — Glanceable, Always-On Display (Project 1)

- **Date:** 2026-06-14
- **Status:** Draft for review
- **Scope:** The Claude Code statusline HUD (`clean-statusline`). Display/UX only.
- **Repo:** `NewCoder3294/clean-mcp-trust-hud`, branch `feat/trust-hud`

## Context

The Trust-HUD renders a 3-row statusline in Claude Code:

1. model · context meter · current task
2. repo · branch
3. **TRUST** — overall gauge + per-metric bars (the clean-mcp layer)

Three problems make row 3 unhelpful in daily use:

1. **Overwhelming.** Row 3 shows 5 metrics, each as `label + 10-cell bar + number` —
   ~15 things to parse. It reads as a dashboard, not a gauge. You can't use it to make
   a snap "trust it / glance / stop" decision while building.
2. **Goes dark.** The score-writing hook marks any unsupported-language file
   (`skipped: true`) — and the statusline drops row 3 entirely when `skipped` is true
   (`statusline.py:347`). Because the user's daily work is Swift/iOS (unsupported;
   clean parses Python/JS/TS only), row 3 vanishes constantly.
3. **Pinned to the wrong repo.** Row 2/3 anchor to the *last scored file's* directory
   (`statusline.py:417-419`), not where you actually are. One Swift edit in
   `strvx-mobile` pins the label to `strvx-mobile` even after you've moved to another repo.

The scoring engine itself is fine: `clean-mcp-trust-hud` is fully indexed (908 Python
entities) and a real score renders correctly when triggered. The fixes here are all in
the display/state layer.

## Goals

Make row 3 a **glanceable, always-honest gauge** that follows you across repos:

- **G1 — Follow me.** Row 2/3 reflect the *current* repo (cwd), never a stale
  last-scored file.
- **G2 — Never go dark.** Every repo/file state renders an honest one-liner — including
  unsupported languages and un-indexed repos — instead of a blank row.
- **G3 — Glanceable verdict (Variant 3).** Lead with one colored verdict + score; when
  not green, name the single most actionable thing — ideally the actual hallucinated
  call(s). The 5-metric breakdown moves to the `clean-hud` dashboard (on-demand), not
  the always-on statusline.

## Non-Goals (explicitly deferred to Project 2)

This project does **not** change behavior — it only changes display. The
hallucination *guardrail* is a separate project:

- **Tier 1 — Nudge:** PostToolUse hook feeds flagged symbols back to Claude so it
  self-corrects.
- **Tier 2 — Gate:** PreToolUse hook scores proposed content (`score_change`) and
  blocks high-confidence hallucinated writes (config `off → warn → block`).

Project 1 is Tier 0 (Show) and the foundation Project 2 builds on. Project 2 gets its
own spec → plan → implementation cycle.

## Design

### 1. Follow-me anchoring (G1)

Row 2 (repo/branch) derives from the **current working directory** — `workspace.current_dir`
in the Claude Code payload (falling back to `cwd` / `os.getcwd()`), via `git_context()`.
The last-scored-file anchoring is removed.

Row 3's numbers are loaded for the **cwd's repo** by `project_id` (see §2). If the most
recent score belongs to a different repo, its numbers are not shown for the current repo.

### 2. Per-repo score memory (G2)

Today a single global `~/.clean/scoring.json` holds the most recent event and gets
clobbered by whatever file was last touched (including skipped Swift files). Replace the
statusline's source of truth with a **per-repo store**:

- `~/.clean/scoring/<project_id>.json` — the last **non-skipped** (good) score for that
  repo. Written by the scoring hook only when `skipped` is false.
- `~/.clean/scoring.json` — retained as the **most-recent-event** marker (any file,
  including skipped). Used only to detect "the file you just touched in *this* repo was
  unsupported," so row 3 can say so while still showing the repo's last good number.

The statusline:

1. Resolves cwd → `(repo, branch, project_id)` via `git_context()`.
2. Loads the per-repo good score for `project_id` (if any).
3. Reads the recent-event marker to detect a just-skipped file in the current repo.
4. Determines `indexed` via the existing index metadata (`metadata.db` `projects` row for
   `project_id`) — cheap lookup, only when no good score exists.

Skipped scores never overwrite a repo's last good score, so "last good" persists across
Swift sessions.

### 3. Row 3 state machine + Variant 3 format (G2, G3)

Row 3 renders exactly one of the following. Color is keyed to the verdict: green ≥ 85
(OK), amber 60–84 (REVIEW), red < 60 (RISK). `●` = live, `○` = last-good / not-live, dim
grey = informational.

| State | Condition | Row 3 |
|---|---|---|
| **OK** | live good score, ≥ 85 | `● OK 96` |
| **REVIEW** | live good score, 60–84 | `● REVIEW 71 · check 2 calls: load_index, warm_model` |
| **RISK** | live good score, < 60 | `● RISK 38 · likely hallucinated: load_index, warm_model` |
| **Last-good** | indexed; current file skipped (unsupported) | `○ 71 REVIEW · last good · Swift not scored` |
| **Not scored** | indexed; no good score yet | `clean · edit a Py/JS/TS file to score` |
| **Not indexed** | repo not in the index | `clean · not indexed — index NewCoder3294/clean-mcp-trust-hud` |
| **Not a repo** | cwd not in a git repo | *(row 3 dropped; HUD is 2 rows)* |

**Green is calm, not absent.** OK renders the one-liner `● OK 96` rather than disappearing
— it avoids layout jump and reassures you the HUD is watching and all-clear. (Open
decision below if you'd rather it vanish.)

**Reason selection (the `· …` suffix), in priority order:**

1. **Grounding offenders present** → `check N call(s): name1, name2` (REVIEW) /
   `likely hallucinated: name1, name2` (RISK). This is the actionable, killer signal, so
   it always wins when present.
2. **Otherwise** → the lowest-scoring displayed metric, mapped to a plain phrase:
   - `blast_radius` → `high blast radius`
   - `orphan` → `low reuse`
   - `alignment` → `off-pattern`
   - `duplication` → `near-duplicate`

Symbol lists cap at **2 names**, with `+N` when more (e.g. `check 2 calls: a, b +3`).
Names come straight from the persisted `offenders[].name` (already on disk —
`state.py:40-43`). No new scoring work.

The full per-metric breakdown (today's row 3) moves to `clean-hud` so it's available on
demand without crowding the always-on strip.

## Affected files

- `src/clean/scoring/statusline.py` — anchoring (§1), per-repo lookup (§2), the row-3
  state machine + Variant 3 rendering and reason selection (§3). The bulk of the work.
- `src/clean/scoring/state.py` — per-repo store: write good scores to
  `scoring/<project_id>.json`, reader keyed by `project_id`; keep recent-event marker.
- `src/clean/scoring/hook.py` / writer call site — route good scores to the per-repo
  store; never let a skipped score overwrite a good one.
- `src/clean/scoring/dashboard.py` (`clean-hud`) — ensure the full 5-metric breakdown
  lives here (it already does; verify parity after trimming the statusline).
- `tests/` — see below.

## Testing

All render logic is pure functions over fixture state — no daemon, no model, no network.

- **State machine:** one test per row-3 state (OK / REVIEW / RISK / last-good / not-scored
  / not-indexed / not-a-repo) asserting exact text (color-stripped).
- **Reason selection:** grounding offenders win over weak metrics; weak-metric mapping;
  symbol capping (`a, b +3`); empty offenders → metric phrase.
- **Anchoring:** row 2/3 follow cwd; a score for a different `project_id` is not shown for
  the current repo.
- **Per-repo store:** good score written to `scoring/<project_id>.json`; skipped score
  does not overwrite last good; reader returns the right repo's score.
- **Color thresholds:** ≥85 green, 60–84 amber, <60 red (existing `_color`).

Keep `fail_under = 60` coverage. Follow the repo's existing test style and the user's
testing rules (single logical assertion per test, deterministic, mock the filesystem via
tmp paths).

## Roadmap

1. **Project 1 (this doc)** — glanceable, always-on display. Tier 0.
2. **Project 2 — Hallucination guardrail.** Tier 1 (nudge the agent via PostToolUse) then
   Tier 2 (gate writes via PreToolUse + `score_change`, behind `off → warn → block`).
   Separate spec.

## Resolved decisions

- **Green-state behavior:** **calm one-liner `● OK 96`** — row 3 stays present when
  all-clear (no layout jump; reassures the HUD is watching). Decided 2026-06-14.
