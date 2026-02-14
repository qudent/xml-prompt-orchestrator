# Agent Guide - XML Prompt Orchestrator

This repo is intentionally split into small modules. Keep each source file under ~500 lines.

## File Map

- `orchestrator.py`
  - Compatibility wrapper + executable entrypoint.
  - Re-exports key symbols so older tests/tools can still `import orchestrator`.

- `xml_orchestrator/cli.py`
  - CLI argument parsing.
  - Constructs and runs `WatchLoop`.

- `xml_orchestrator/loop.py`
  - Core runtime state machine.
  - Watches for file changes, starts tmux runs, checks completion, writes assistant output.
  - Includes stale-save recovery for active runs (if manual editor save removes `id`/`running` markers).

- `xml_orchestrator/watcher.py`
  - Linux inotify watcher wrapper with poll fallback behavior.

- `xml_orchestrator/backend.py`
  - Backend command construction (`codex` / `claude`).
  - Streaming output parsing to `(session_id, final_message)`.

- `xml_orchestrator/xml_ops.py`
  - XML tree operations: pending detection, middle-edit forks, assistant insertion, git annotations.

- `xml_orchestrator/storage.py`
  - Canonical XML serialization and atomic writes.
  - Read/write helpers and path normalization for log links.

- `xml_orchestrator/constants.py`
  - Shared XML tag constants and inotify mask constants.

- `tests/test_orchestrator.py`
  - Unit tests + integration-style tests using mocked tmux subprocess behavior.

## Editing Rules

- Prefer extending module-specific files over growing `orchestrator.py`.
- Keep business logic out of shell scripts.
- Add/adjust tests for any loop behavior changes, especially around:
  - active run lifecycle
  - stale editor resaves
  - assistant writeback placement
- If module boundaries shift, update this file and `STATUS.md` in the same commit.
