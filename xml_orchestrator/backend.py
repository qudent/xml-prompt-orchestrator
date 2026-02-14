"""Backend command planning and output parsing."""

from __future__ import annotations

import json
import re
from typing import Optional


def build_backend_command(backend: str, prompt: str, session_id: Optional[str]) -> list[str]:
    backend = backend.strip().lower()
    if backend == "codex":
        if session_id:
            return ["codex", "exec", "resume", session_id, "--json", prompt]
        return ["codex", "exec", "--json", prompt]
    if backend == "claude":
        base = ["claude", "-p", "--output-format", "stream-json"]
        if session_id:
            return base + ["-r", session_id, prompt]
        return base + [prompt]
    raise ValueError(f"unsupported backend: {backend}")


def parse_backend_output(backend: str, text: str) -> tuple[Optional[str], str]:
    backend = backend.strip().lower()
    session_id = None
    final_message = ""

    if backend == "codex":
        for line in text.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started":
                session_id = event.get("thread_id")
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    final_message = item.get("text", "") or final_message
        if session_id is None:
            match = re.search(r"session id:\s*([0-9a-fA-F-]{8,})", text)
            if match:
                session_id = match.group(1)

    elif backend == "claude":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = event.get("session_id") or event.get("sessionId") or session_id
                message_text = event.get("text") or event.get("message", {}).get("content") or ""
                if isinstance(message_text, str) and message_text.strip():
                    final_message = message_text
            else:
                final_message = line
    else:
        raise ValueError(f"unsupported backend: {backend}")

    return session_id, final_message.strip()
