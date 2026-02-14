# XML Prompt Orchestrator - Status

## Current State
Runtime is modularized under `xml_orchestrator/` with all implementation files under ~500 lines. The watcher now launches runs from save diffs, supports parallel active questions, and defers normal prompt id writeback until assistant completion so id+assistant persist together.

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

## Blockers
- None.
- Backend/network interruptions can still yield partial/no final assistant messages for a run; those are surfaced as `status="error"` assistant nodes.

## Recent Results
- Reworked `WatchLoop` for multi-run state (`active_runs`) instead of single-run state.
- Added unresolved-human signature diffing to determine launch candidates per save.
- Removed pre-answer marker writes from normal starts; completion writes id+assistant together.
- Added regression test: `test_start_defers_id_write_until_completion`.
- Added regression test: `test_diff_save_launches_parallel_runs_without_duplicates`.
- Existing stale-resave and tmux lifecycle integration tests still pass.
- Live verification on `/home/name/Dropbox/xml-orchestrator-test-20260214-110942`:
  - added two humans in one save
  - both received distinct assistant replies (`P1`, `P2`)
  - watcher session is running with updated code.

## Next Steps
1. Optional: add visible heartbeat/progress timestamp for long-running runs.
2. Optional: add configurable max-turn timeout and auto-cancel note.
3. Optional: migrate old historical `running="true"` artifacts in existing test XMLs.
