# XML Prompt Orchestrator - Status

## Current State
Planning is active with owner feedback now incorporated into `tasks/prd-xml-prompt-orchestrator.md`. Several decisions are resolved, several are still open, and implementation will follow TDD once final decisions are locked.

## Active Goals
- [x] Create repository and baseline docs
  - [x] Initialize git repo
  - [x] Add `README.md`
  - [x] Add `tasks/` and planning artifacts
- [x] Define v1 product requirements
  - [x] Capture XML-inspired single-file workflow
  - [x] Capture branch/fork behavior for mid-history edits
  - [x] Capture per-message git hash annotation requirement
  - [x] Add background tmux execution + cleanup requirement
  - [x] Add Codex resume/log metadata requirement
- [ ] Resolve open product decisions from PRD
  - [x] Message ID policy: UUIDs, but short/human-readable form preferred
  - [x] Fork detection: edit to non-tip human message triggers fork
  - [x] First-run invocation: `codex exec "<prompt>"` in tmux
  - [x] Resume policy: use stored `session_id`; if missing, start new session (no `--last` fallback)
  - [x] Timeout policy: default no timeout; consider explicit kill mechanism
  - [x] Write ownership: orchestrator writes XML file, not Codex process
  - [x] Backend scope: include Codex + Claude support in v1
  - [ ] File model and canonical rewrite policy
  - [ ] Active-branch selection model vs structural branch inference
  - [ ] Downstream handling policy after mid-history edit
  - [ ] Metadata persistence depth (`session_id`, log path, raw output)
  - [ ] Git annotation policy (`HEAD` vs `HEAD+dirty` vs auto-commit)
  - [ ] No-HEAD bootstrap behavior
  - [ ] Concurrency policy during active run (latest-only vs FIFO vs restart)
  - [ ] Failure writeback shape in XML
- [ ] Implement minimal v1 orchestrator with TDD after decisions are finalized
  - [ ] Write tests first for parser + fork detection + command planner
  - [ ] Implement minimal runtime to satisfy tests
  - [ ] Add integration test for tmux run + output capture + XML rewrite

## Blockers
- Owner questions need direct answers on branch semantics and log metadata rationale.
- Remaining unresolved decisions still affect storage format and run-control flow.

## Recent Results
- Reviewed local coordination and antipattern guidance before planning.
- Created repo at `~/repos/xml-prompt-orchestrator`.
- Wrote PRD: `tasks/prd-xml-prompt-orchestrator.md`.
- Incorporated new requirement: Codex runs in disposable background tmux sessions with accessible logs and resumable session annotation.
- Corrected command terminology after docs check: replace `codex -print -resume` with Codex-native `codex exec` / `codex exec resume`.
- Expanded open questions into a full decision matrix (15 questions) with recommended defaults to reduce ambiguity before implementation.
- Ran a live Codex CLI check (`codex exec` and `codex exec --json`) and confirmed it emits a final assistant message that can be captured and written by the orchestrator.
- Added explicit TDD requirement for implementation process.

## Next Steps
1. Commit owner PRD feedback and status update.
2. Reply to owner’s inline questions with concrete recommendations.
3. Finalize unresolved decisions in PRD.
4. Start TDD implementation (`tests -> minimal code -> integration check`).
