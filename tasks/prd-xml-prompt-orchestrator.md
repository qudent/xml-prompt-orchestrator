# PRD: XML Prompt Orchestrator

## 1. Introduction / Overview
Build a very small local orchestrator that uses one editable conversation file as the control surface for Codex runs.  
When the user saves a new human prompt, the orchestrator should launch a one-off Codex process in background `tmux`, capture output, write assistant replies back into the conversation structure, and annotate each message with git state metadata.

The system must stay intentionally simple and readable: short code, minimal moving parts, no heavy framework.

## 2. Goals
- Keep a single human-facing conversation file as the workflow center.
- Trigger one-shot `codex exec` automatically on save when a new human prompt is detected.
- Represent conversation history in an XML-inspired format that can encode forks.
- When a mid-history edit occurs, create a branch/fork instead of mutating prior branch history.
- Annotate every message with:
  - short git commit hash for repo state at message completion
  - Codex resume/log identifier (when available)
- Run Codex in temporary background `tmux` sessions and clean up sessions after completion.

## 3. User Stories

### US-001: Edit one conversation file
**Description:** As a human operator, I want to edit one text file so I can drive the orchestrator without extra UI.

**Acceptance Criteria:**
- [ ] One designated file path is watched for save events.
- [ ] File can contain human prompts and assistant replies in XML-inspired structure.
- [ ] Canonical rewrite keeps deterministic ordering and formatting.

### US-002: Trigger Codex on new human prompt
**Description:** As a human operator, I want new prompts to run automatically so I do not manually invoke Codex each time.

**Acceptance Criteria:**
- [ ] On save, newly added human message at branch tip is detected.
- [ ] Orchestrator launches `codex exec` for first-run prompts.
- [ ] For continuation runs, orchestrator uses `codex exec resume <session-id>` or `codex exec resume --last`.
- [ ] Assistant output is inserted into the conversation file under the same branch.

### US-003: Run in background tmux and preserve logs
**Description:** As a human operator, I want Codex runs to happen in background sessions with recoverable logs.

**Acceptance Criteria:**
- [ ] Each run uses a fresh named `tmux` session.
- [ ] Session output is persisted to a log file with stable run id.
- [ ] If Codex prints a resume/session id, it is parsed and stored in message metadata.
- [ ] `tmux` session is terminated after success/failure/timeout cleanup.

### US-004: Fork when editing in the middle
**Description:** As a human operator, I want historical edits to branch so previous outcomes remain visible.

**Acceptance Criteria:**
- [ ] Editing a non-tip human message creates a new branch id.
- [ ] Prior branch content is preserved and still addressable.
- [ ] New assistant output is attached only to the new branch lineage.

### US-005: Annotate each message with git state
**Description:** As a human operator, I want every message tied to repo state so I can correlate discussion and code state.

**Acceptance Criteria:**
- [ ] Every message has a `git` metadata field with short hash (e.g. `a1b2c3d`).
- [ ] Hash represents repository state at end of that message write.
- [ ] Behavior for dirty tree / missing commit is explicit and deterministic.

## 4. Functional Requirements
- FR-1: The system must watch exactly one configured conversation file path.
- FR-2: The system must parse the file into a conversation tree with branch-aware message IDs.
- FR-3: The system must normalize and rewrite the file to canonical XML-inspired text after each accepted save.
- FR-4: A newly added human message at current branch tip must schedule one Codex run.
- FR-5: Codex invocation must use Codex-native non-interactive commands (`codex exec`, optionally `codex exec resume`).
- FR-6: Each Codex run must execute in a dedicated `tmux` session.
- FR-7: Session stdout/stderr must be captured into a timestamped log file.
- FR-8: If available, Codex resume/session identifier must be extracted and stored in metadata.
- FR-9: After completion, the tmux session must be killed automatically.
- FR-10: Mid-history edits must create a new branch/fork identifier.
- FR-11: Existing branch history must not be deleted during fork creation.
- FR-12: Assistant replies must be written under the active branch only.
- FR-13: Every written message must include short git hash annotation.
- FR-14: If `HEAD` is unavailable, fallback annotation must be consistent (e.g. `no-head`).
- FR-15: Write operations must be atomic to avoid partial file corruption.
- FR-16: The script should be small and readable with minimal dependencies.
- FR-17: Implementation should follow test-driven development for parser, fork logic, and command orchestration.
- FR-18: Cancellation must use a simple attribute on an existing user message tag (`killed="true"`), not a dedicated control node.
- FR-19: The format must remain easy to edit in plain text editors without extra command syntax blocks.

## 5. Non-Goals (Out of Scope)
- Multi-user collaboration or remote syncing.
- GUI/editor plugin UI beyond file edits.
- Rich XML schema validation engine.
- Automatic conflict resolution across concurrent editors.
- Running multiple Codex jobs in parallel for one file (initial version).

## 6. Design Considerations
- Keep XML human-readable and line-editable.
- Favor explicit tags/attributes over dense shorthand.
- Preserve stable message IDs so diffs remain understandable.
- Prefer one script plus one config file max for v1.
- Plain-text-editor first: control intent should be encoded as simple attributes on normal message tags.
- No separate `<control .../>` structure in v1.

## 7. Technical Considerations
- Candidate implementation language: Python 3 (standard library first).
- Use TDD: write failing tests first, then minimal implementation, then refactor for readability.
- File watch can be mtime polling loop (simple) or optional watchdog dependency.
- `tmux capture-pane` or redirected shell output can provide logs.
- Parsing "resume session with ..." text should tolerate small output variations.
- Git metadata source: `git rev-parse --short HEAD` plus dirty-state policy.
- Terminology normalization:
  - Codex CLI: `codex exec` = non-interactive mode; `resume` is a subcommand, not a `--resume` flag.
  - Claude Code CLI (reference only): `-p/--print` and `-r/--resume` are flags there; do not apply these names to Codex commands.

## 8. Success Metrics
- New human prompt to assistant reply round-trip works without manual command entry.
- Conversation file remains valid and readable after 50+ iterative edits.
- Fork creation is deterministic for repeated mid-history edits.
- Operator can resume a prior Codex session from stored metadata in under 30 seconds.

## 9. Locked Decisions
- D-1: Source of truth is one XML file; user edits and canonical rewrite happen in that same file.
- D-2: Canonical rewrite runs on every valid save.
- D-3: Message IDs use short UUID-style IDs (human-readable, not full-length UUID strings).
- D-4: Any text change to a non-tip `<human>` message creates a fork.
- D-5: On fork, old downstream path is preserved; new branch is created from the edit point.
- D-6: No explicit active-branch field. Branch is inferred from XML structure and edit location.
- D-7: First run uses backend non-interactive invocation in tmux (`codex exec "<prompt>"` pattern).
- D-8: Resume uses stored `session_id`; if missing, start a new session (no `--last` fallback).
- D-9: Persist `session_id` and tmux log path in metadata. Final assistant answer from backend output is written into the XML as the assistant message text.
- D-10: Default is no timeout. Cancellation is user-driven by setting `killed="true"` on the target `<human>` message.
- D-11: Git annotation stores `head_short` plus `dirty` flag (no auto-commit).
- D-12: If repository has no commits, annotate `head_short="no-head"` and continue.
- D-13: During an active run, keep only the latest pending save. Orchestrator owns all file writes; backend process never writes XML directly.
- D-14: Failed runs produce an `<assistant status="error">` node with short summary.
- D-15: v1 supports both Codex and Claude backends.
