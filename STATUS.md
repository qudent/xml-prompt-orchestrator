# XML Prompt Orchestrator - Status

## Current State
v1 is implemented and test-covered in this repo. The project now has a working `orchestrator.py`, unit tests, locked design decisions in the PRD, and a configured Ralph loop (`scripts/ralph/`) with project-specific `prd.json` and `progress.txt`. Ralph smoke-run has been executed and returned `<promise>COMPLETE</promise>`.

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
- [x] Configure Ralph loop for this project
  - [x] Add `scripts/ralph/ralph.sh`
  - [x] Add `scripts/ralph/prd.json` with story tracking
  - [x] Add `scripts/ralph/progress.txt`
  - [x] Add project quality command to `scripts/ralph/CODEX.md` and `scripts/ralph/CLAUDE.md`

## Blockers
- None for v1 implementation.
- Future blocker risk: real-world backend output shape changes may require parser adjustments.

## Recent Results
- Added `orchestrator.py` implementing XML parsing, canonical writes, fork creation, backend invocation, tmux lifecycle, and cancellation handling.
- Added `tests/test_orchestrator.py` with tests for command generation, output parsing, pending detection, and middle-edit forking.
- Locked the PRD into explicit decisions and removed open-question ambiguity.
- Added Ralph loop files under `scripts/ralph/` and converted project plan into `scripts/ralph/prd.json`.
- Added `.gitignore` entries for Python cache and orchestrator runtime logs.
- Ran a live smoke test: XML watcher executed Codex in tmux, captured `session_id`, and wrote assistant response back into the file.
- Ran `scripts/ralph/ralph.sh --tool codex 1`; loop completed with `<promise>COMPLETE</promise>` and moved work to branch `ralph/xml-prompt-orchestrator-v1`.
- Added ignore rules for Ralph runtime files (`scripts/ralph/.last-branch`, `scripts/ralph/archive/`) to keep worktree clean.
- Updated Ralph prompt templates to explicitly reference `scripts/ralph/prd.json` and `scripts/ralph/progress.txt`.

## Next Steps
1. Add one integration test that simulates tmux lifecycle and assistant writeback with a fake backend command.
2. If desired, continue iterative work on `ralph/xml-prompt-orchestrator-v1` via `scripts/ralph/ralph.sh`.
