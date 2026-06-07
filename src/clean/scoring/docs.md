# scoring/ — Trust-HUD

A local, terminal-native trust layer that scores AI-agent-written code against
the indexed codebase. When an agent edits a file, the change is parsed and run
through a set of **pluggable indicators**; the result is an overall 0–100 score
(100 = safest) plus per-indicator scores and the specific flagged symbols,
surfaced live in the terminal.

Everything is local — no cloud, no telemetry — and built on data clean-mcp
already computes (the call graph, embeddings, and incremental/staleness state).

## Status

| Component | Status |
|-----------|--------|
| Indicator registry + service | active |
| Indicators: grounding, blast_radius, index_trust, orphan | active |
| Indicators: alignment, duplication (embedding-based) | active |
| Scoring daemon + hook + statusline | active |
| MCP tools `score_file` / `score_change` | active |
| Import-aware grounding (resolve imported symbols) | active |
| Storing imports in the index (cross-file import resolution) | planned |

## Contents

| File | Purpose |
|------|---------|
| `base.py` | `Indicator` base class + value objects (`IndicatorResult`, `Offender`, `ScoringContext`, `FileScore`). `ScoringContext` memoizes name lookups and embeddings shared across indicators. |
| `registry.py` | `@register_indicator` decorator + `IndicatorRegistry.build_enabled()`. |
| `service.py` | `ScoringService` — parse a file, run enabled indicators, aggregate a `FileScore`. |
| `allowlists.py` | Per-language builtin/global/stdlib allowlists (precision-first grounding). |
| `classify.py` | `classify()` + `RefKind` — decides which call-sites are verifiable. |
| `similarity.py` | `cosine()` and `is_self_match()` for the embedding indicators. |
| `state.py` | `ScoringStateWriter` — persists the latest score to `~/.clean/scoring.json`. |
| `daemon.py` | Persistent scorer holding a warm embedding model (unix socket). |
| `hook.py` | `clean-score` entry point: PostToolUse hook + `serve` subcommand. |
| `statusline.py` | `clean-statusline` entry point: renders the HUD line. |
| `indicators/` | One file per indicator; `__init__.py` imports them so they self-register. |

## The indicators

| Key | Label | Embedding? | Measures |
|-----|-------|-----------|----------|
| `grounding` | Grounding | no | % of referenced symbols that actually exist (anti-hallucination) |
| `blast_radius` | Blast | no | how many existing callers a changed symbol has |
| `index_trust` | Index | no | whether the index is fresh enough to trust the scores (file-level) |
| `orphan` | Orphan | no | newly written symbols nothing references |
| `alignment` | Alignment | yes | drift from the indexed version / fit to existing patterns |
| `duplication` | Dup | yes | near-duplicate of code already in the index |

### Grounding precision

Grounding only flags a reference as hallucinated when it is a **bare,
non-builtin identifier** (or an unresolved `self.`/`this.` method) that is
absent from the edited file, its **imports**, and the index. Anything
dotted/imported/builtin is treated as acceptable. Imports are resolved at
score-time from the edited file's own source (`imports.py`) — so
`from collections import defaultdict; defaultdict()` and
`import {useState} from 'react'; useState()` are correctly *not* flagged. This
favors precision (few false positives). See `classify.py`, `allowlists.py`,
and `imports.py`. A future step stores imports in the index for cross-file
import resolution.

## Adding an indicator

Write a subclass of `Indicator` in `indicators/`, decorate it with
`@register_indicator`, add its module import to `indicators/__init__.py`, and
add its key to `ScoringConfig.enabled_indicators` (or rely on the "all" default).
Nothing else changes.

## Conventions

- Indicators return a normalized **0–100** score (100 = best/safest) and never
  raise — the service wraps each in try/except and degrades to a skipped result.
- When the project is not indexed, indicators set `skipped=True, confidence=0`;
  when the index is stale, they lower `confidence` (the service weights overall
  score by confidence).
- Entity-level indicators are aggregated per file by **worst (min) score** with
  the union of offenders; file-level indicators (`file_level = True`) run once.

## Surface / wiring

- `ServiceContainer.scoring` (see `../services/container.py`) exposes a
  `ScoringService`. The MCP server (`../local/mcp_server.py`) exposes
  `score_file` and `score_change` tools.
- Config lives in `ScoringConfig` (`../core/config.py`), env-overridable via
  `CLEAN_SCORING_*` (`ENABLED`, `INDICATORS`, `STATE_PATH`, `DUP_THRESHOLD`,
  `DRIFT_THRESHOLD`, `BLAST_WARN`).
- Terminal HUD (add to your Claude Code `settings.json`):
  ```json
  { "hooks": { "PostToolUse": [ { "matcher": "Edit|Write|MultiEdit",
        "hooks": [{ "type": "command", "command": "clean-score hook" }] } ] },
    "statusLine": { "type": "command", "command": "clean-statusline" } }
  ```
  Start the warm daemon with `clean-score serve` (optional; the hook falls back
  to the no-model indicators if it isn't running).

## Tests

`tests/unit/scoring/` (per-indicator + classify/registry/state; helpers in
`helpers.py`, path-injected by `conftest.py`),
`tests/integration/test_scoring_service.py`, and
`tests/e2e/test_score_mcp_tool.py`.
