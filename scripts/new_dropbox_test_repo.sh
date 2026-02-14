#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="${1:-xml-orchestrator-test-$(date +%Y%m%d-%H%M%S)}"
BACKEND="${2:-codex}"

if [[ "$BACKEND" != "codex" && "$BACKEND" != "claude" ]]; then
  echo "Error: backend must be 'codex' or 'claude' (got '$BACKEND')." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ORCHESTRATOR_PY="$PROJECT_ROOT/orchestrator.py"

DROPBOX_DIR="$HOME/Dropbox"
REPO_DIR="$DROPBOX_DIR/$REPO_NAME"
ORCHESTRATION_FILE="$REPO_DIR/orchestration.xml"

for cmd in git tmux python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: required command not found: $cmd" >&2
    exit 1
  fi
done

if [[ ! -f "$ORCHESTRATOR_PY" ]]; then
  echo "Error: orchestrator not found at $ORCHESTRATOR_PY" >&2
  exit 1
fi

if [[ ! -d "$DROPBOX_DIR" ]]; then
  echo "Error: Dropbox directory not found at $DROPBOX_DIR" >&2
  exit 1
fi

if [[ -e "$REPO_DIR" ]]; then
  echo "Error: target path already exists: $REPO_DIR" >&2
  echo "Try another name: $0 my-new-test-repo" >&2
  exit 1
fi

mkdir -p "$REPO_DIR"
if ! git -C "$REPO_DIR" init -b main >/dev/null 2>&1; then
  git -C "$REPO_DIR" init >/dev/null
  git -C "$REPO_DIR" branch -M main >/dev/null 2>&1 || true
fi

cat > "$REPO_DIR/README.md" <<EOF
# $REPO_NAME

Local Dropbox test repo for xml-prompt-orchestrator.

## Quick start

1. The watcher is already running in tmux (printed by the setup script).
2. Open \`orchestration.xml\` in any text editor.
3. Add a new trailing \`<human>\` message and save.
4. Wait a moment, then re-open/save to see inserted \`<assistant>\` output.

Example:

\`\`\`xml
<human id="h1">Reply with exactly: OK</human>
\`\`\`

## Notes

- Use only one active trailing \`<human>\` at a time.
- Set \`killed="true"\` on a running \`<human>\` to cancel.
- Runtime logs are in \`.xml-orchestrator/logs/\`.
EOF

cat > "$REPO_DIR/.gitignore" <<'EOF'
.xml-orchestrator/
EOF

cat > "$ORCHESTRATION_FILE" <<EOF
<conversation backend="$BACKEND">
  <usage>
    <step>Add a trailing &lt;human id="h1"&gt;...&lt;/human&gt; and save to trigger a run.</step>
    <step>Assistant output will be inserted as a following &lt;assistant&gt; node.</step>
    <step>Set killed="true" on a running &lt;human&gt; to cancel.</step>
    <step>For full instructions, see README.md.</step>
  </usage>
</conversation>
EOF

git -C "$REPO_DIR" add README.md .gitignore orchestration.xml
git -C "$REPO_DIR" commit -m "chore: initialize orchestrator test repo" >/dev/null

SAFE_NAME="$(echo "$REPO_NAME" | tr -cs 'A-Za-z0-9_' '_')"
SESSION_NAME="xml_orch_test_${SAFE_NAME}_$(date +%H%M%S)"

printf -v ORCH_CMD 'cd %q && python3 %q %q --repo %q --watch-mode auto --poll-seconds 1.0' \
  "$PROJECT_ROOT" "$ORCHESTRATOR_PY" "$ORCHESTRATION_FILE" "$REPO_DIR"
tmux new-session -d -s "$SESSION_NAME" "$ORCH_CMD"

echo "Created test repo and started watcher."
echo "repo_path=$REPO_DIR"
echo "orchestration_file=$ORCHESTRATION_FILE"
echo "tmux_session=$SESSION_NAME"
echo "Edit this file now: $ORCHESTRATION_FILE"
echo "Stop watcher: tmux kill-session -t $SESSION_NAME"
