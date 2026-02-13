# XML Prompt Orchestrator

A tiny local tool that treats one text file as the source of truth for a Codex conversation tree.

Core idea:
- You edit a single conversation file.
- Saving with a new human prompt spawns one-shot `codex -print -resume`.
- The assistant response is written back into the same file.
- Editing earlier messages creates a forked branch.
- Each message is tagged with a short git commit hash for repo state tracking.

Planning docs:
- `STATUS.md`
- `tasks/prd-xml-prompt-orchestrator.md`
