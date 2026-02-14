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

## Quick Start

1. Create a conversation file:

```xml
<conversation backend="codex">
  <human id="h1">Reply with exactly: OK</human>
</conversation>
```

2. Run the watcher:

```bash
python orchestrator.py /path/to/conversation.xml --repo /path/to/repo --watch-mode auto
```

3. Edit and save the XML file in any plain text editor:
- New `<human>` tip message triggers a backend run.
- Assistant output is inserted as `<assistant>`.
- Editing a non-tip `<human>` creates a `<branch>`.
- Set `killed="true"` on a running `<human>` to cancel it.

## Ralph Loop

Ralph loop files are in `scripts/ralph/`.

```bash
./scripts/ralph/ralph.sh --tool codex 10
```
