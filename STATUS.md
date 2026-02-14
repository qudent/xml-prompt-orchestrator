# XML Prompt Orchestrator - Status

## Current State
v1 runtime is stable and now split into focused modules under `xml_orchestrator/` so no implementation file exceeds ~500 lines. The stale-save writeback bug is fixed: assistant output is recovered even if an editor save removes active human `id`/`running` markers during an in-flight run.

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
- Operational risk remains that very large prompts can produce long-running backend turns; runtime handles this but UX can appear "stuck" while `running="true"`.

## Recent Results
- Diagnosed missing assistant writeback in Dropbox test repo to stale overwrite of active human markers.
- Implemented robust active-human resolution and output recovery path.
- Added integration test: `test_integration_recover_writeback_after_stale_human_resave`.
- Refactored monolithic `orchestrator.py` into modular package files:
  - `backend.py`, `xml_ops.py`, `storage.py`, `watcher.py`, `loop.py`, `cli.py`.
- Added root `AGENTS.md` with architecture and file responsibilities.
- Restarted live watcher for `/home/name/Dropbox/xml-orchestrator-test-20260214-110942`.
- Test suite passes: `python3 -m unittest discover -s tests -v`.

## Next Steps
1. Optional: add a visible heartbeat/progress timestamp on running `<human>` nodes.
2. Optional: add a configurable max-turn timeout and auto-cancel note in XML.
3. Keep module boundaries aligned with `AGENTS.md` as behavior grows.
