#!/usr/bin/env python3
"""Tiny XML prompt orchestrator for Codex/Claude backends."""

from __future__ import annotations

import argparse
import copy
import ctypes
import json
import os
import re
import select
import shlex
import struct
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HUMAN_TAG = "human"
ASSISTANT_TAG = "assistant"
BRANCH_TAG = "branch"

# Linux inotify constants.
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_CREATE = 0x00000100
IN_DELETE_SELF = 0x00000400
IN_IGNORED = 0x00008000
IN_MOVE_SELF = 0x00000800
IN_MOVED_TO = 0x00000080
IN_Q_OVERFLOW = 0x00004000


class LinuxInotifyWatcher:
    """Watch a single file path via inotify events on its parent directory."""

    _HEADER = struct.Struct("iIII")
    _MASK = (
        IN_ATTRIB
        | IN_CLOSE_WRITE
        | IN_CREATE
        | IN_DELETE_SELF
        | IN_IGNORED
        | IN_MOVE_SELF
        | IN_MOVED_TO
        | IN_Q_OVERFLOW
    )

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.fd: Optional[int] = None
        self.wd: Optional[int] = None
        self._libc: Optional[ctypes.CDLL] = None
        if os.name != "posix":
            return
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.inotify_init1.argtypes = [ctypes.c_int]
            libc.inotify_init1.restype = ctypes.c_int
            libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            libc.inotify_add_watch.restype = ctypes.c_int
        except OSError:
            return
        self._libc = libc
        self._open()

    @property
    def available(self) -> bool:
        return self.fd is not None and self.wd is not None

    def _open(self) -> None:
        if self._libc is None:
            return
        flags = os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        fd = self._libc.inotify_init1(flags)
        if fd < 0:
            return
        self.fd = fd
        self._ensure_watch()

    def _ensure_watch(self) -> None:
        if self._libc is None or self.fd is None:
            return
        dir_bytes = os.fsencode(str(self.file_path.parent))
        wd = self._libc.inotify_add_watch(self.fd, ctypes.c_char_p(dir_bytes), self._MASK)
        if wd < 0:
            self.close()
            return
        self.wd = wd

    def wait(self, timeout_seconds: Optional[float]) -> bool:
        if self.fd is None or self.wd is None:
            if timeout_seconds is not None:
                time.sleep(timeout_seconds)
            return False
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout_seconds)
        except OSError:
            return False
        if not ready:
            return False

        changed = False
        while True:
            try:
                raw = os.read(self.fd, 64 * 1024)
            except BlockingIOError:
                break
            except OSError:
                break
            if not raw:
                break
            offset = 0
            while offset + self._HEADER.size <= len(raw):
                wd, mask, _cookie, name_len = self._HEADER.unpack_from(raw, offset)
                offset += self._HEADER.size
                raw_name = raw[offset : offset + name_len]
                offset += name_len
                name = raw_name.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

                if mask & IN_Q_OVERFLOW:
                    changed = True
                    continue
                if mask & (IN_IGNORED | IN_DELETE_SELF | IN_MOVE_SELF):
                    changed = True
                    self.wd = None
                    self._ensure_watch()
                    continue
                if wd != self.wd:
                    continue
                if name and name != self.file_path.name:
                    continue
                changed = True
        return changed

    def close(self) -> None:
        if self.fd is None:
            return
        try:
            os.close(self.fd)
        except OSError:
            pass
        finally:
            self.fd = None
            self.wd = None


def new_short_id() -> str:
    return uuid.uuid4().hex[:8]


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
                session_id = (
                    event.get("session_id")
                    or event.get("sessionId")
                    or session_id
                )
                message_text = (
                    event.get("text")
                    or event.get("message", {}).get("content")
                    or ""
                )
                if isinstance(message_text, str) and message_text.strip():
                    final_message = message_text
            else:
                final_message = line
    else:
        raise ValueError(f"unsupported backend: {backend}")
    return session_id, final_message.strip()


def find_message_by_id(root: ET.Element, message_id: str) -> Optional[ET.Element]:
    for node in root.iter():
        if node.get("id") == message_id:
            return node
    return None


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _siblings(parent: ET.Element, node: ET.Element) -> list[ET.Element]:
    return list(parent)


def _node_index(parent: ET.Element, node: ET.Element) -> int:
    for idx, child in enumerate(list(parent)):
        if child is node:
            return idx
    raise ValueError("node not found in parent")


def _insert_after(parent: ET.Element, node: ET.Element, new_node: ET.Element) -> None:
    idx = _node_index(parent, node)
    parent.insert(idx + 1, new_node)


def _human_text(node: ET.Element) -> str:
    return (node.text or "").strip()


def _has_following_assistant(parent: ET.Element, human: ET.Element) -> bool:
    siblings = _siblings(parent, human)
    idx = _node_index(parent, human)
    for sibling in siblings[idx + 1 :]:
        if sibling.tag == ASSISTANT_TAG:
            return True
        if sibling.tag == HUMAN_TAG:
            return False
    return False


def _previous_assistant_session(parent: ET.Element, human: ET.Element) -> Optional[str]:
    siblings = _siblings(parent, human)
    idx = _node_index(parent, human)
    for sibling in reversed(siblings[:idx]):
        if sibling.tag != ASSISTANT_TAG:
            continue
        session_id = sibling.get("session_id")
        if session_id:
            return session_id
    return None


def apply_middle_edit_forks(current_root: ET.Element, previous_root: Optional[ET.Element]) -> int:
    if previous_root is None:
        return 0
    previous_text_by_id = {
        node.get("id"): _human_text(node)
        for node in previous_root.iter(HUMAN_TAG)
        if node.get("id")
    }
    changed = 0
    parent_map = _parent_map(current_root)
    for human in list(current_root.iter(HUMAN_TAG)):
        message_id = human.get("id")
        if not message_id or message_id not in previous_text_by_id:
            continue
        current_text = _human_text(human)
        old_text = previous_text_by_id[message_id]
        if current_text == old_text:
            continue
        parent = parent_map.get(human)
        if parent is None:
            continue
        if not _has_following_assistant(parent, human):
            continue

        # Preserve old branch by restoring original message text.
        human.text = old_text
        branch = ET.Element(BRANCH_TAG, {"id": new_short_id(), "from": message_id})
        fork_human = ET.Element(HUMAN_TAG, {"id": new_short_id(), "forked_from": message_id})
        fork_human.text = current_text
        resume_from = _previous_assistant_session(parent, human)
        if resume_from:
            fork_human.set("resume_from", resume_from)
        branch.append(fork_human)
        _insert_after(parent, human, branch)
        changed += 1
    return changed


def find_pending_human(root: ET.Element) -> Optional[ET.Element]:
    parent_map = _parent_map(root)
    for human in root.iter(HUMAN_TAG):
        if (human.get("killed", "")).lower() == "true":
            continue
        if (human.get("running", "")).lower() == "true":
            continue
        parent = parent_map.get(human)
        if parent is None:
            continue
        if _has_following_assistant(parent, human):
            continue
        return human
    return None


def git_state(repo_path: Path) -> tuple[str, bool]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        head = "no-head"

    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return head, bool(dirty)


def annotate_git(root: ET.Element, repo_path: Path) -> None:
    head, dirty = git_state(repo_path)
    dirty_text = "true" if dirty else "false"
    for node in root.iter():
        if node.tag not in (HUMAN_TAG, ASSISTANT_TAG):
            continue
        node.set("head_short", head)
        node.set("dirty", dirty_text)


def canonical_xml_text(root: ET.Element) -> str:
    root_copy = copy.deepcopy(root)
    ET.indent(root_copy, space="  ")
    return ET.tostring(root_copy, encoding="unicode") + "\n"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent) as tmp:
        tmp.write(text)
        temp_name = tmp.name
    os.replace(temp_name, path)


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists():
        current_text = path.read_text(encoding="utf-8")
        if current_text == text:
            return False
    atomic_write(path, text)
    return True


def read_root(path: Path) -> ET.Element:
    if not path.exists():
        root = ET.Element("conversation", {"backend": "codex"})
        atomic_write(path, canonical_xml_text(root))
        return root
    return ET.parse(path).getroot()


def relative_log_path(repo_path: Path, log_path: Path) -> str:
    try:
        return str(log_path.relative_to(repo_path))
    except ValueError:
        return str(log_path)


def insert_assistant_after_human(
    root: ET.Element,
    human_id: str,
    *,
    text: str,
    status: str,
    session_id: Optional[str],
    log_path: Path,
    repo_path: Path,
) -> bool:
    target = find_message_by_id(root, human_id)
    if target is None:
        return False
    parent = _parent_map(root).get(target)
    if parent is None:
        return False
    assistant = ET.Element(ASSISTANT_TAG, {"id": new_short_id(), "status": status})
    assistant.text = text
    if session_id:
        assistant.set("session_id", session_id)
    assistant.set("log_path", relative_log_path(repo_path, log_path))
    _insert_after(parent, target, assistant)
    return True


@dataclass
class ActiveRun:
    session_name: str
    backend: str
    human_id: str
    log_path: Path


class WatchLoop:
    def __init__(
        self,
        conversation_file: Path,
        repo_path: Path,
        poll_seconds: float = 1.0,
        use_inotify: bool = True,
    ):
        self.conversation_file = conversation_file
        self.repo_path = repo_path
        self.poll_seconds = poll_seconds
        self.logs_dir = repo_path / ".xml-orchestrator" / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.previous_root: Optional[ET.Element] = None
        self.last_mtime = 0.0
        self.active_run: Optional[ActiveRun] = None
        self.watcher: Optional[LinuxInotifyWatcher] = None
        if use_inotify:
            watcher = LinuxInotifyWatcher(self.conversation_file)
            if watcher.available:
                self.watcher = watcher

    def run(self) -> None:
        try:
            while True:
                self.tick()
                self._wait_for_next_tick()
        finally:
            if self.watcher is not None:
                self.watcher.close()

    def _wait_for_next_tick(self) -> None:
        timeout = self.poll_seconds if self.active_run is not None else None
        if self.watcher is not None:
            self.watcher.wait(timeout)
            return
        if timeout is None:
            timeout = self.poll_seconds
        time.sleep(timeout)

    def tick(self) -> None:
        if self.active_run is not None:
            self._check_active_run()

        if not self.conversation_file.exists():
            root = read_root(self.conversation_file)
            self.previous_root = copy.deepcopy(root)
            self.last_mtime = self.conversation_file.stat().st_mtime
            return

        current_mtime = self.conversation_file.stat().st_mtime
        if current_mtime <= self.last_mtime:
            return
        self.last_mtime = current_mtime
        self._process_save()

    def _process_save(self) -> None:
        root = read_root(self.conversation_file)
        apply_middle_edit_forks(root, self.previous_root)
        annotate_git(root, self.repo_path)

        if self.active_run is not None:
            active = find_message_by_id(root, self.active_run.human_id)
            if active is not None and (active.get("killed", "")).lower() == "true":
                self._kill_active("killed by user")
                insert_assistant_after_human(
                    root,
                    self.active_run.human_id,
                    text="Run cancelled (killed=true).",
                    status="error",
                    session_id=None,
                    log_path=self.active_run.log_path,
                    repo_path=self.repo_path,
                )
                self.active_run = None

        if self.active_run is None:
            pending = find_pending_human(root)
            if pending is not None:
                self._start_run(root, pending)

        self._write_root(root)
        self.previous_root = copy.deepcopy(root)

    def _write_root(self, root: ET.Element) -> bool:
        changed = write_if_changed(self.conversation_file, canonical_xml_text(root))
        if changed:
            self.last_mtime = self.conversation_file.stat().st_mtime
        return changed

    def _start_run(self, root: ET.Element, human: ET.Element) -> None:
        backend = root.get("backend", "codex").lower()
        human_id = human.get("id") or new_short_id()
        human.set("id", human_id)
        prompt = _human_text(human)
        if not prompt:
            return
        session_id = human.get("resume_from") or self._find_resume_for_human(root, human)
        cmd = build_backend_command(backend, prompt, session_id)

        run_id = new_short_id()
        session_name = f"xml_orch_{run_id}"
        log_path = self.logs_dir / f"{run_id}.log"
        shell_cmd = f"cd {shlex.quote(str(self.repo_path))} && {shlex.join(cmd)} > {shlex.quote(str(log_path))} 2>&1"
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name, shell_cmd], check=True)

        human.set("running", "true")
        human.set("log_path", relative_log_path(self.repo_path, log_path))
        self.active_run = ActiveRun(
            session_name=session_name,
            backend=backend,
            human_id=human_id,
            log_path=log_path,
        )

    def _find_resume_for_human(self, root: ET.Element, human: ET.Element) -> Optional[str]:
        parent = _parent_map(root).get(human)
        if parent is None:
            return None
        return _previous_assistant_session(parent, human)

    def _session_exists(self, session_name: str) -> bool:
        proc = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            check=False,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0

    def _kill_active(self, reason: str) -> None:
        if self.active_run is None:
            return
        subprocess.run(
            ["tmux", "kill-session", "-t", self.active_run.session_name],
            check=False,
            capture_output=True,
            text=True,
        )
        with self.active_run.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n# orchestrator: {reason}\n")

    def _check_active_run(self) -> None:
        if self.active_run is None:
            return
        if self._session_exists(self.active_run.session_name):
            return
        subprocess.run(
            ["tmux", "kill-session", "-t", self.active_run.session_name],
            check=False,
            capture_output=True,
            text=True,
        )
        root = read_root(self.conversation_file)
        target = find_message_by_id(root, self.active_run.human_id)
        if target is not None:
            target.attrib.pop("running", None)

        output = self.active_run.log_path.read_text(encoding="utf-8") if self.active_run.log_path.exists() else ""
        session_id, message = parse_backend_output(self.active_run.backend, output)
        if not message:
            message = "No assistant output captured."
            status = "error"
        else:
            status = "ok"

        insert_assistant_after_human(
            root,
            self.active_run.human_id,
            text=message,
            status=status,
            session_id=session_id,
            log_path=self.active_run.log_path,
            repo_path=self.repo_path,
        )
        annotate_git(root, self.repo_path)
        self._write_root(root)
        self.previous_root = copy.deepcopy(root)
        self.last_mtime = self.conversation_file.stat().st_mtime
        self.active_run = None


def main() -> None:
    parser = argparse.ArgumentParser(description="XML prompt orchestrator")
    parser.add_argument("conversation_file", help="Path to conversation XML file")
    parser.add_argument("--repo", default=".", help="Git repo path (default: .)")
    parser.add_argument("--poll-seconds", type=float, default=1.0, help="Watch polling interval")
    parser.add_argument(
        "--watch-mode",
        choices=("auto", "poll"),
        default="auto",
        help="File watch mode: 'auto' uses inotify when available, 'poll' disables inotify.",
    )
    args = parser.parse_args()

    conversation_file = Path(args.conversation_file).resolve()
    repo_path = Path(args.repo).resolve()
    loop = WatchLoop(
        conversation_file=conversation_file,
        repo_path=repo_path,
        poll_seconds=args.poll_seconds,
        use_inotify=(args.watch_mode == "auto"),
    )
    loop.run()


if __name__ == "__main__":
    main()
