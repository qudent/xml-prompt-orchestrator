# XML Prompt Orchestrator - Status

## Current State
Runtime is modularized under `xml_orchestrator/` with implementation files under ~500 lines. The watcher now auto-normalizes free text into `<human>` nodes, forks newly inserted middle messages, appends bottom messages in-place, launches runs from save diffs, supports parallel active questions, and defers prompt-id writeback until completion so `id+assistant` are persisted together.

## Active Goals
- [x] Finalize product decisions
  - [x] Single XML source-of-truth with canonical rewrite
  - [x] Fork-on-middle-edit with preserved original branch
  - [x] Plain-editor cancellation via `killed="true"` on `<human>`
  - [x] Backend support in v1: Codex + Claude
  - [x] Git annotation policy: `head_short` + `dirty` (`no-head` fallback)
- [x] Implement minimal orchestrator runtime with TDD
  - [x] Backend command planner and output parser
  - [x] Fork detection and branch creation logic
  - [x] Watch loop and tmux lifecycle
  - [x] Assistant writeback and log linking
- [x] Fix Dropbox churn / self-write loop
  - [x] No-op write suppression (`write_if_changed`)
  - [x] Linux inotify watch mode with polling fallback
- [x] Fix stale-save active-run writeback loss
  - [x] Resolve active human by signature/text fallback
  - [x] Preserve output with recovered node if anchor is missing
  - [x] End-to-end stale-resave regression test
- [x] Refactor runtime into smaller files and document layout
- [x] Switch to diff-based parallel launch model
  - [x] Launch only new/changed unresolved humans per save diff
  - [x] Allow multiple concurrent active runs
  - [x] Avoid duplicate relaunch on pure resaves
  - [x] Keep tmux cleanup on completion/cancel
- [x] Implement plain-text anywhere auto-heal semantics
  - [x] Wrap bare text nodes into `<human>` in `conversation`/`branch`
  - [x] Fork only newly introduced middle humans (baseline-aware)
  - [x] Keep bottom appended humans on main line
  - [x] Ensure second save while first run is active launches isolated context

## Blockers
- None.
- Backend/network interruptions can still yield partial/no final assistant messages for a run; these are written as `status="error"` assistant nodes.

## Recent Results
- Added malformed-XML auto-recovery path that converts user free text into a new `<human>` instead of crashing parse flow.
- Updated middle insertion logic to use baseline diffing so existing answered humans are not re-forked.
- Added integration-style test coverage for:
  - plain text middle insertion -> branch fork + resume linkage
  - plain text bottom append across consecutive saves -> new run per save + isolated second run context
  - pure re-save no-op launch behavior
- Full test suite currently passing: `python3 -m unittest discover -s tests -v` (13 tests).

## Next Steps
1. Optional: add visible heartbeat/progress timestamp for long-running runs.
2. Optional: add configurable max-turn timeout and auto-cancel note.
3. Optional: migrate old historical `running="true"` artifacts in existing test XMLs.
