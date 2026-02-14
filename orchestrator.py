#!/usr/bin/env python3
"""Compatibility wrapper and script entrypoint for XML prompt orchestrator."""

from __future__ import annotations

import xml_orchestrator.loop as _loop_module
from xml_orchestrator.backend import build_backend_command, parse_backend_output
from xml_orchestrator.cli import main
from xml_orchestrator.loop import ActiveRun, WatchLoop
from xml_orchestrator.storage import write_if_changed
from xml_orchestrator.watcher import LinuxInotifyWatcher
from xml_orchestrator.xml_ops import (
    annotate_git,
    apply_middle_edit_forks,
    find_message_by_id,
    find_pending_human,
    insert_assistant_after_human,
    new_short_id,
)

# Backward-compatible hook for tests that patch `orchestrator.subprocess.run`.
subprocess = _loop_module.subprocess

__all__ = [
    "ActiveRun",
    "LinuxInotifyWatcher",
    "WatchLoop",
    "annotate_git",
    "apply_middle_edit_forks",
    "build_backend_command",
    "find_message_by_id",
    "find_pending_human",
    "insert_assistant_after_human",
    "main",
    "new_short_id",
    "parse_backend_output",
    "subprocess",
    "write_if_changed",
]


if __name__ == "__main__":
    main()
