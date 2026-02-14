# XML Prompt Orchestrator - Status

## Current State
v1 is implemented, test-covered, and patched to avoid self-triggering save loops in Dropbox-backed repos. Watch mode defaults to Linux inotify when available (`--watch-mode auto`) with polling fallback, and unchanged canonical XML is no longer rewritten.

## Active Goals
- [x] Finalize product decisions
  - [x] Single XML source-of-truth with canonical rewrite
  - [x] Fork-on-middle-edit with preserved original branch
  - [x] Plain-editor cancellation via `killed="true"` on `<human>`
  - [x] Backend support in v1: Codex + Claude
  - [x] Git annotation policy: `head_short` + `dirty` (`no-head` fallback)
- [x] Implement minimal orchestrator runtime with TDD
  - [x] Add failing tests first
  - [x] Implement backend command planner and output parser
  - [x] Implement fork detection and branch creation logic
  - [x] Implement watch loop, tmux launch/cleanup, and assistant writeback
  - [x] Verify tests pass
- [x] Fix Dropbox churn / self-write loop
  - [x] Identify loop source (`_write_root` always rewriting)
  - [x] Add content-aware write guard (`write_if_changed`)
  - [x] Add Linux inotify watcher with polling fallback
  - [x] Add regression test for no-op write behavior
  - [x] Verify Dropbox returns to steady state after stopping pollers
- [x] Add one integration test for tmux lifecycle + assistant writeback

## Blockers
- None for current local workflow.
- Future risk: backend output format drift may require parser updates.

## Recent Results
- Diagnosed Dropbox backlog growth to two active orchestrator pollers writing files under `~/Dropbox` every second.
- Confirmed pending Dropbox count grew continuously while pollers ran, then drained quickly after stopping them.
- Implemented no-op write suppression so unchanged canonical XML does not update mtime.
- Added `LinuxInotifyWatcher` and `--watch-mode {auto,poll}` CLI option.
- Updated bootstrap script to launch watcher with `--watch-mode auto`.
- Added regression test `test_write_if_changed_skips_identical_content`.
- Added integration test `test_integration_tmux_lifecycle_and_assistant_writeback`.
- Test suite passes: `python3 -m unittest discover -s tests -v`.
- Launched a fresh live Dropbox test repo and watcher:
  - repo: `/home/name/Dropbox/xml-orchestrator-test-20260214-110942`
  - session: `xml_orch_test_xml_orchestrator_test_20260214_110942__110942`

## Next Steps
1. Manually edit the live `orchestration.xml` in the new test repo and verify assistant writeback.
2. Consider ignoring high-churn generated paths (for example `.venv`, `.cache`, model artifacts) in Dropbox test repos.
3. Optionally expose a `--once` debug mode for deterministic local troubleshooting.
