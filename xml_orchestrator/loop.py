"""Main orchestrator watch loop and tmux run lifecycle."""

from __future__ import annotations

import copy
import shlex
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .backend import build_backend_command, parse_backend_output
from .constants import HUMAN_TAG
from .storage import canonical_xml_text, read_root, relative_log_path, write_if_changed
from .watcher import LinuxInotifyWatcher
from .xml_ops import (
    annotate_git,
    apply_middle_edit_forks,
    find_message_by_id,
    find_pending_human,
    has_following_assistant,
    human_text,
    insert_assistant_after_human,
    new_short_id,
    parent_map,
    previous_assistant_session,
)


@dataclass
class ActiveRun:
    session_name: str
    backend: str
    human_id: str
    human_text: str
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
        import time

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
            active = self._resolve_active_human(root)
            if active is not None and (active.get("killed", "")).lower() == "true":
                active.attrib.pop("running", None)
                self._kill_active("killed by user")
                insert_assistant_after_human(
                    root,
                    self.active_run.human_id,
                    text="Run cancelled (killed=true).",
                    status="error",
                    session_id=None,
                    log_path_value=self._active_log_value(),
                )
                self.active_run = None
            elif active is not None:
                self._apply_active_markers(active)

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
        prompt = human_text(human)
        if not prompt:
            return

        session_id = human.get("resume_from") or self._find_resume_for_human(root, human)
        cmd = build_backend_command(backend, prompt, session_id)

        run_id = new_short_id()
        session_name = f"xml_orch_{run_id}"
        log_path = self.logs_dir / f"{run_id}.log"
        shell_cmd = (
            f"cd {shlex.quote(str(self.repo_path))} && "
            f"{shlex.join(cmd)} > {shlex.quote(str(log_path))} 2>&1"
        )
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name, shell_cmd], check=True)

        human.set("running", "true")
        human.set("log_path", relative_log_path(self.repo_path, log_path))
        self.active_run = ActiveRun(
            session_name=session_name,
            backend=backend,
            human_id=human_id,
            human_text=prompt,
            log_path=log_path,
        )

    def _find_resume_for_human(self, root: ET.Element, human: ET.Element) -> Optional[str]:
        parent = parent_map(root).get(human)
        if parent is None:
            return None
        return previous_assistant_session(parent, human)

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

    def _active_log_value(self) -> str:
        if self.active_run is None:
            return ""
        return relative_log_path(self.repo_path, self.active_run.log_path)

    def _apply_active_markers(self, human: ET.Element) -> None:
        if self.active_run is None:
            return
        human.set("id", self.active_run.human_id)
        human.set("running", "true")
        human.set("log_path", self._active_log_value())

    def _resolve_active_human(self, root: ET.Element) -> Optional[ET.Element]:
        if self.active_run is None:
            return None

        target = find_message_by_id(root, self.active_run.human_id)
        if target is not None:
            return target

        parents = parent_map(root)
        unresolved: list[ET.Element] = []
        target_log = self._active_log_value()
        for human in root.iter(HUMAN_TAG):
            parent = parents.get(human)
            if parent is None:
                continue
            if has_following_assistant(parent, human):
                continue
            unresolved.append(human)
            if target_log and human.get("log_path") == target_log:
                return human

        for human in unresolved:
            if human_text(human) == self.active_run.human_text:
                return human

        if unresolved:
            return unresolved[-1]
        return None

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
        target = self._resolve_active_human(root)
        if target is not None:
            self._apply_active_markers(target)
            target.attrib.pop("running", None)
        else:
            # Preserve completed output even if a stale save removed active ids.
            target = ET.Element(HUMAN_TAG, {"id": self.active_run.human_id, "recovered": "true"})
            target.text = self.active_run.human_text
            root.append(target)

        output = self.active_run.log_path.read_text(encoding="utf-8") if self.active_run.log_path.exists() else ""
        session_id, message = parse_backend_output(self.active_run.backend, output)
        status = "ok"
        if not message:
            message = "No assistant output captured."
            status = "error"

        insert_assistant_after_human(
            root,
            self.active_run.human_id,
            text=message,
            status=status,
            session_id=session_id,
            log_path_value=self._active_log_value(),
        )

        annotate_git(root, self.repo_path)
        self._write_root(root)
        self.previous_root = copy.deepcopy(root)
        self.last_mtime = self.conversation_file.stat().st_mtime
        self.active_run = None
