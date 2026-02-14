"""CLI entrypoint for XML prompt orchestrator."""

from __future__ import annotations

import argparse
from pathlib import Path

from .loop import WatchLoop


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
