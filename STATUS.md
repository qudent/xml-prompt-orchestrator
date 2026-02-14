# XML Prompt Orchestrator - Status

## Current State
v1 runtime is stable and modularized under `xml_orchestrator/` with no implementation file above ~500 lines. Stale-save writeback loss is fixed: assistant output is recovered even if a manual save strips active `id`/`running` markers while a turn is in flight.

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
  - [x] Watch loop, tmux launch/cleanup, assistant writeback
  - [x] Unit and integration test coverage
- [x] Fix Dropbox churn / self-write loop
  - [x] No-op write suppression (`write_if_changed`)
  - [x] Linux inotify watch mode with polling fallback
- [x] Fix stale-save active-run writeback loss
  - [x] Resolve active human by id/log/text/last-unresolved fallback
  - [x] Rehydrate active markers during in-flight saves
  - [x] Preserve output with recovered human node when anchor is missing
  - [x] Add end-to-end regression test
- [x] Refactor runtime into smaller files and document layout

## Blockers
- None.
- Very large prompts can still create long-running backend turns; XML now clearly shows `running="true"` until completion or cancellation.

## Recent Results
- Diagnosed missing assistant writeback to stale overwrite of active human markers.
- Implemented robust active-human recovery and output-preservation path.
- Added integration test: `test_integration_recover_writeback_after_stale_human_resave`.
- Refactored monolithic runtime into:
  - `backend.py`, `xml_ops.py`, `storage.py`, `watcher.py`, `loop.py`, `cli.py`
- Added root `AGENTS.md` describing file responsibilities and update rules.
- Fixed cancellation cleanup so killed turns remove `running` marker before cancellation assistant insertion.
- Restarted live watcher for `/home/name/Dropbox/xml-orchestrator-test-20260214-110942`.
- Verified live repo now appends assistant output normally on new short prompt (`Please reply with exactly: OK` -> `OK`).
- Test suite passes: `python3 -m unittest discover -s tests -v`.

## Next Steps
1. Optional: add a visible heartbeat/progress timestamp for long-running turns.
2. Optional: add configurable max-turn timeout and auto-cancel note.
3. Keep `AGENTS.md` in sync with architecture changes.
