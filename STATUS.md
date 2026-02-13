# XML Prompt Orchestrator - Status

## Current State
Planning phase complete. The repo is initialized and a full PRD exists at `tasks/prd-xml-prompt-orchestrator.md`. CLI terminology has been normalized against docs (Codex `exec`/`exec resume` vs Claude `-p`/`-r`). Implementation is intentionally paused until core behavior decisions are confirmed to avoid redesign churn.

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
  - [ ] File model (single file vs editable+generated split)
  - [ ] Fork downstream handling policy
  - [ ] Git hash policy (`HEAD` only vs auto-commit vs dirty+hash)
  - [ ] Resume metadata depth (token only vs token+log)
  - [ ] Save conflict policy while run is active
- [ ] Implement minimal v1 orchestrator after decisions are finalized

## Blockers
- Waiting on owner answers to the 5 PRD questions in section "Open Questions".
- No coding should start yet, because unresolved decisions directly affect storage format and control flow.

## Recent Results
- Reviewed local coordination and antipattern guidance before planning.
- Created repo at `~/repos/xml-prompt-orchestrator`.
- Wrote PRD: `tasks/prd-xml-prompt-orchestrator.md`.
- Incorporated new requirement: Codex runs in disposable background tmux sessions with accessible logs and resumable session annotation.
- Corrected command terminology after docs check: replace `codex -print -resume` with Codex-native `codex exec` / `codex exec resume`.

## Next Steps
1. Get answers to PRD Open Questions (reply format: `1A, 2B, 3C, ...`).
2. Lock canonical XML schema and run lifecycle from those answers.
3. Build smallest readable implementation (`watch -> parse -> run codex in tmux -> rewrite XML`).
