# Agent Guide - XML Prompt Orchestrator

This repo is intentionally split into small modules. Keep each source file under ~500 lines.

## Behavioral Contract

- The watcher launches runs from XML save diffs only.
- The watcher can run multiple backend turns in parallel.
- For normal runs, a prompt's `id` and assistant response are written together at completion (single writeback event).
- Completed/canceled runs must clean up their tmux session.

## File Map

- `orchestrator.py`
  - Compatibility wrapper + executable entrypoint.
  - Re-exports key symbols so older tests/tools can still `import orchestrator`.

- `xml_orchestrator/cli.py`
  - CLI argument parsing.
  - Constructs and runs `WatchLoop`.

- `xml_orchestrator/loop.py`
  - Core runtime state machine.
  - Save-diff detection, parallel run launch, tmux lifecycle, and assistant writeback.
  - Active-run target recovery if user edits/resaves while runs are in flight.

- `xml_orchestrator/watcher.py`
  - Linux inotify watcher wrapper with poll fallback behavior.

- `xml_orchestrator/backend.py`
  - Backend command construction (`codex` / `claude`).
  - Streaming output parsing to `(session_id, final_message)`.

- `xml_orchestrator/xml_ops.py`
  - XML tree operations: middle-edit forks, assistant insertion, git annotations.

- `xml_orchestrator/storage.py`
  - Canonical XML serialization and atomic writes.
  - Read/write helpers and path normalization for log links.

- `xml_orchestrator/constants.py`
  - Shared XML tag constants and inotify mask constants.

- `tests/test_orchestrator.py`
  - Unit tests + integration-style tests using mocked tmux subprocess behavior.
  - Includes regression tests for stale resaves, diff-based launches, and deferred id writeback.

## Editing Rules

- Prefer extending module-specific files over growing `orchestrator.py`.
- Keep business logic out of shell scripts.
- Add/adjust tests for loop behavior changes, especially around:
  - save-diff launch detection
  - parallel active runs
  - stale editor resaves
  - assistant writeback placement
  - tmux cleanup
- If module boundaries or runtime semantics shift, update this file and `STATUS.md` in the same commit.
