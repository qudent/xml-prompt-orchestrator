"""Main orchestrator watch loop and tmux run lifecycle."""

from __future__ import annotations

import copy
import hashlib
import html
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
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
    fork_new_middle_humans,
    has_following_assistant,
    human_text,
    insert_assistant_after_human,
    normalize_free_text_humans,
    new_short_id,
    parent_map,
    previous_assistant_session,
)


@dataclass
class HumanCandidate:
    element: ET.Element
    signature: str
    text: str


@dataclass
class ActiveRun:
    session_name: str
    backend: str
    human_id: str
    signature: str
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
        self.active_runs: dict[str, ActiveRun] = {}

        self.watcher: Optional[LinuxInotifyWatcher] = None
        if use_inotify:
            watcher = LinuxInotifyWatcher(self.conversation_file)
            if watcher.available:
                self.watcher = watcher

    @property
    def active_run(self) -> Optional[ActiveRun]:
        # Backward-compatible convenience accessor used by older tests/tools.
        if len(self.active_runs) == 1:
            return next(iter(self.active_runs.values()))
        return None

    def run(self) -> None:
        try:
            while True:
                self.tick()
                self._wait_for_next_tick()
        finally:
            if self.watcher is not None:
                self.watcher.close()

    def _wait_for_next_tick(self) -> None:
        timeout = self.poll_seconds if self.active_runs else None
        if self.watcher is not None:
            self.watcher.wait(timeout)
            return
        if timeout is None:
            timeout = self.poll_seconds

        import time

        time.sleep(timeout)

    def tick(self) -> None:
        if self.active_runs:
            self._check_active_runs()

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
        root, changed = self._read_root_with_autofix()
        changed = normalize_free_text_humans(root) > 0 or changed
        changed = apply_middle_edit_forks(root, self.previous_root) > 0 or changed
        changed = fork_new_middle_humans(root, self.previous_root) > 0 or changed

        # Handle user-triggered cancellations for any active run.
        for run in list(self.active_runs.values()):
            target = self._resolve_target_human(root, run, include_killed=True)
            if target is None:
                continue
            if (target.get("killed", "")).lower() != "true":
                continue

            self._kill_run(run, "killed by user")
            self._finalize_run(
                root,
                run,
                session_id=None,
                message="Run cancelled (killed=true).",
                status="error",
                target=target,
            )
            changed = True

        # Launch only newly introduced/changed unresolved humans from this save diff.
        for candidate in self._new_launch_candidates(root):
            self._start_run(root, candidate)

        # Persist only actual structural mutations (for example forking, cancellation writeback).
        if changed:
            annotate_git(root, self.repo_path)
            self._write_root(root)

        self.previous_root = copy.deepcopy(root)

    def _write_root(self, root: ET.Element) -> bool:
        changed = write_if_changed(self.conversation_file, canonical_xml_text(root))
        if changed:
            self.last_mtime = self.conversation_file.stat().st_mtime
        return changed

    def _collect_unresolved_candidates(
        self,
        root: ET.Element,
        *,
        include_killed: bool,
    ) -> list[HumanCandidate]:
        parents = parent_map(root)
        text_counts: dict[str, int] = {}
        candidates: list[HumanCandidate] = []

        for human in root.iter(HUMAN_TAG):
            parent = parents.get(human)
            if parent is None:
                continue
            if has_following_assistant(parent, human):
                continue
            if not include_killed and (human.get("killed", "")).lower() == "true":
                continue

            text = human_text(human)
            message_id = human.get("id")
            if message_id:
                signature = f"id:{message_id}"
            else:
                digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
                text_counts[digest] = text_counts.get(digest, 0) + 1
                signature = f"text:{digest}:{text_counts[digest]}"
            candidates.append(HumanCandidate(element=human, signature=signature, text=text))

        return candidates

    def _new_launch_candidates(self, root: ET.Element) -> list[HumanCandidate]:
        current = self._collect_unresolved_candidates(root, include_killed=False)
        if self.previous_root is None:
            previous: list[HumanCandidate] = []
        else:
            previous = self._collect_unresolved_candidates(self.previous_root, include_killed=False)

        previous_counts = Counter(candidate.signature for candidate in previous)
        launches: list[HumanCandidate] = []

        for candidate in current:
            if previous_counts[candidate.signature] > 0:
                previous_counts[candidate.signature] -= 1
                continue
            if self._has_active_signature(candidate.signature):
                continue
            launches.append(candidate)

        return launches

    def _has_active_signature(self, signature: str) -> bool:
        return any(run.signature == signature for run in self.active_runs.values())

    def _start_run(self, root: ET.Element, candidate: HumanCandidate) -> None:
        backend = root.get("backend", "codex").lower()
        prompt = candidate.text
        if not prompt:
            return

        explicit_resume = candidate.element.get("resume_from")
        if explicit_resume:
            session_id = explicit_resume
        elif self.active_runs:
            # Isolation rule: parallel runs should not inherit context from each other.
            session_id = None
        else:
            session_id = self._find_resume_for_human(root, candidate.element)
        cmd = build_backend_command(backend, prompt, session_id)

        run_id = new_short_id()
        session_name = f"xml_orch_{run_id}"
        log_path = self.logs_dir / f"{run_id}.log"
        shell_cmd = (
            f"cd {shlex.quote(str(self.repo_path))} && "
            f"{shlex.join(cmd)} > {shlex.quote(str(log_path))} 2>&1"
        )
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name, shell_cmd], check=True)

        message_id = candidate.element.get("id") or new_short_id()
        self.active_runs[message_id] = ActiveRun(
            session_name=session_name,
            backend=backend,
            human_id=message_id,
            signature=candidate.signature,
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

    def _kill_run(self, run: ActiveRun, reason: str) -> None:
        subprocess.run(
            ["tmux", "kill-session", "-t", run.session_name],
            check=False,
            capture_output=True,
            text=True,
        )
        with run.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n# orchestrator: {reason}\n")

    def _run_log_value(self, run: ActiveRun) -> str:
        return relative_log_path(self.repo_path, run.log_path)

    def _resolve_target_human(
        self,
        root: ET.Element,
        run: ActiveRun,
        *,
        include_killed: bool,
    ) -> Optional[ET.Element]:
        # If id is already present in file, prefer exact id match.
        target = find_message_by_id(root, run.human_id)
        if target is not None:
            return target

        candidates = self._collect_unresolved_candidates(root, include_killed=include_killed)

        # Best effort: same unresolved signature from launch diff model.
        for candidate in candidates:
            if candidate.signature == run.signature:
                return candidate.element

        # Fallback: same prompt text.
        for candidate in candidates:
            if candidate.text == run.human_text:
                return candidate.element

        # Final fallback to avoid dropping output.
        if candidates:
            return candidates[-1].element
        return None

    def _finalize_run(
        self,
        root: ET.Element,
        run: ActiveRun,
        *,
        session_id: Optional[str],
        message: str,
        status: str,
        target: Optional[ET.Element],
    ) -> None:
        if target is None:
            # Preserve output even if stale saves removed the original target.
            target = ET.Element(HUMAN_TAG, {"id": run.human_id, "recovered": "true"})
            target.text = run.human_text
            root.append(target)
        else:
            target.set("id", run.human_id)

        target.attrib.pop("running", None)
        target.set("log_path", self._run_log_value(run))

        insert_assistant_after_human(
            root,
            run.human_id,
            text=message,
            status=status,
            session_id=session_id,
            log_path_value=self._run_log_value(run),
        )

        annotate_git(root, self.repo_path)
        self._write_root(root)
        self.previous_root = copy.deepcopy(root)
        self.last_mtime = self.conversation_file.stat().st_mtime

        self.active_runs.pop(run.human_id, None)

    def _check_active_runs(self) -> None:
        for run in list(self.active_runs.values()):
            if self._session_exists(run.session_name):
                continue

            # Ensure run tmux session is removed.
            subprocess.run(
                ["tmux", "kill-session", "-t", run.session_name],
                check=False,
                capture_output=True,
                text=True,
            )

            root, _ = self._read_root_with_autofix()
            target = self._resolve_target_human(root, run, include_killed=True)

            output = run.log_path.read_text(encoding="utf-8") if run.log_path.exists() else ""
            session_id, message = parse_backend_output(run.backend, output)
            status = "ok"
            if not message:
                message = "No assistant output captured."
                status = "error"

            self._finalize_run(
                root,
                run,
                session_id=session_id,
                message=message,
                status=status,
                target=target,
            )

    def _extract_plain_text_candidates(self, raw_text: str) -> list[str]:
        # Best-effort fallback for malformed XML: extract user-typed free text.
        text = re.sub(r"<[^>]+>", "\n", raw_text)
        text = html.unescape(text)
        chunks = [line.strip() for line in text.splitlines() if line.strip()]
        if not chunks:
            return []
        return chunks

    def _read_root_with_autofix(self) -> tuple[ET.Element, bool]:
        try:
            return read_root(self.conversation_file), False
        except ET.ParseError:
            raw = self.conversation_file.read_text(encoding="utf-8", errors="replace")
            if self.previous_root is not None:
                root = copy.deepcopy(self.previous_root)
            else:
                root = ET.Element("conversation", {"backend": "codex"})

            existing = {human_text(node) for node in root.iter(HUMAN_TAG)}
            candidates = self._extract_plain_text_candidates(raw)
            if candidates:
                selected = next((chunk for chunk in reversed(candidates) if chunk not in existing), candidates[-1])
                human = ET.Element(HUMAN_TAG)
                human.text = selected
                root.append(human)
            return root, True
