import copy
import re
import subprocess as py_subprocess
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import orchestrator


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text)


class OrchestratorLogicTests(unittest.TestCase):
    def test_build_backend_command(self) -> None:
        cmd = orchestrator.build_backend_command("codex", "hello", None)
        self.assertEqual(cmd, ["codex", "exec", "--json", "hello"])

        cmd = orchestrator.build_backend_command("codex", "hello", "abc-123")
        self.assertEqual(cmd, ["codex", "exec", "resume", "abc-123", "--json", "hello"])

        cmd = orchestrator.build_backend_command("claude", "hello", "sess-1")
        self.assertEqual(
            cmd,
            ["claude", "-p", "--output-format", "stream-json", "-r", "sess-1", "hello"],
        )

    def test_parse_codex_output_json(self) -> None:
        text = "\n".join(
            [
                '{"type":"thread.started","thread_id":"sess-123"}',
                '{"type":"item.completed","item":{"type":"agent_message","text":"Answer"}}',
            ]
        )
        session_id, final_message = orchestrator.parse_backend_output("codex", text)
        self.assertEqual(session_id, "sess-123")
        self.assertEqual(final_message, "Answer")

    def test_find_pending_human(self) -> None:
        root = parse_xml(
            """
<conversation backend="codex">
  <human id="h1">A</human>
  <assistant id="a1">A1</assistant>
  <human id="h2" killed="true">B</human>
  <human id="h3">C</human>
</conversation>
""".strip()
        )
        pending = orchestrator.find_pending_human(root)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.get("id"), "h3")

    def test_middle_edit_creates_branch_and_restores_old_text(self) -> None:
        previous = parse_xml(
            """
<conversation backend="codex">
  <human id="h1">Question 1</human>
  <assistant id="a1" session_id="sess-1">Answer 1</assistant>
  <human id="h2">Question 2</human>
  <assistant id="a2">Answer 2</assistant>
</conversation>
""".strip()
        )
        current = copy.deepcopy(previous)
        h1 = orchestrator.find_message_by_id(current, "h1")
        assert h1 is not None
        h1.text = "Question 1 edited"

        changed = orchestrator.apply_middle_edit_forks(current, previous)
        self.assertEqual(changed, 1)

        # Original message text is preserved on original branch.
        h1_after = orchestrator.find_message_by_id(current, "h1")
        self.assertEqual((h1_after.text or "").strip(), "Question 1")

        # A new fork branch exists with new human text.
        branches = list(current.findall("branch"))
        self.assertEqual(len(branches), 1)
        fork_human = branches[0].find("human")
        self.assertIsNotNone(fork_human)
        self.assertEqual((fork_human.text or "").strip(), "Question 1 edited")

    def test_write_if_changed_skips_identical_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "orchestration.xml"
            text = "<conversation backend=\"codex\" />\n"
            self.assertTrue(orchestrator.write_if_changed(target, text))
            first_mtime = target.stat().st_mtime_ns
            time.sleep(0.01)
            self.assertFalse(orchestrator.write_if_changed(target, text))
            second_mtime = target.stat().st_mtime_ns
            self.assertEqual(first_mtime, second_mtime)

    def test_integration_tmux_lifecycle_and_assistant_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            conversation = repo / "orchestration.xml"
            conversation.write_text(
                (
                    "<conversation backend=\"codex\">\n"
                    "  <human id=\"h1\">Reply with exactly: OK</human>\n"
                    "</conversation>\n"
                ),
                encoding="utf-8",
            )

            py_subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(
                ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True
            )
            py_subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True
            )
            py_subprocess.run(["git", "add", "orchestration.xml"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            loop = orchestrator.WatchLoop(
                conversation_file=conversation,
                repo_path=repo,
                poll_seconds=0.01,
                use_inotify=False,
            )

            real_run = py_subprocess.run

            def fake_run(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "tmux":
                    if len(cmd) > 1 and cmd[1] == "new-session":
                        shell_cmd = cmd[-1]
                        match = re.search(r">\s*(?:'([^']+)'|(\S+))\s+2>&1", shell_cmd)
                        self.assertIsNotNone(match, "unable to parse tmux log redirection path")
                        log_path = Path(match.group(1) or match.group(2))
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        log_path.write_text(
                            (
                                '{"type":"thread.started","thread_id":"sess-integration"}\n'
                                '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}\n'
                            ),
                            encoding="utf-8",
                        )
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 1, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                loop.tick()
                self.assertIsNotNone(loop.active_run)
                loop.tick()
                self.assertIsNone(loop.active_run)

            root = ET.parse(conversation).getroot()
            human = root.find("human")
            assistant = root.find("assistant")
            self.assertIsNotNone(human)
            self.assertIsNotNone(assistant)
            self.assertEqual((assistant.text or "").strip(), "OK")
            self.assertEqual(assistant.get("status"), "ok")
            self.assertEqual(assistant.get("session_id"), "sess-integration")
            self.assertIsNone(human.get("running"))

    def test_integration_recover_writeback_after_stale_human_resave(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            original_text = (
                "<conversation backend=\"codex\">\n"
                "  <human>Repeat exactly: OK</human>\n"
                "</conversation>\n"
            )
            conversation = repo / "orchestration.xml"
            conversation.write_text(original_text, encoding="utf-8")

            py_subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(
                ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True
            )
            py_subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True
            )
            py_subprocess.run(["git", "add", "orchestration.xml"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            loop = orchestrator.WatchLoop(
                conversation_file=conversation,
                repo_path=repo,
                poll_seconds=0.01,
                use_inotify=False,
            )

            real_run = py_subprocess.run
            session_state = {"running": True}

            def fake_run(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "tmux":
                    if len(cmd) > 1 and cmd[1] == "new-session":
                        shell_cmd = cmd[-1]
                        match = re.search(r">\s*(?:'([^']+)'|(\S+))\s+2>&1", shell_cmd)
                        self.assertIsNotNone(match, "unable to parse tmux log redirection path")
                        log_path = Path(match.group(1) or match.group(2))
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        log_path.write_text(
                            (
                                '{"type":"thread.started","thread_id":"sess-recover"}\n'
                                '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}\n'
                            ),
                            encoding="utf-8",
                        )
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 0 if session_state["running"] else 1, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        session_state["running"] = False
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                # First save starts the run and writes id/running markers.
                loop.tick()
                self.assertIsNotNone(loop.active_run)

                # Simulate stale editor save that overwrites file and removes markers.
                conversation.write_text(original_text, encoding="utf-8")

                # Complete session; writeback should recover target human and not drop output.
                session_state["running"] = False
                loop.tick()
                self.assertIsNone(loop.active_run)

            root = ET.parse(conversation).getroot()
            humans = list(root.findall("human"))
            assistants = list(root.findall("assistant"))
            self.assertGreaterEqual(len(humans), 1)
            self.assertGreaterEqual(len(assistants), 1)
            self.assertEqual((assistants[-1].text or "").strip(), "OK")
            self.assertEqual(assistants[-1].get("status"), "ok")
            self.assertEqual(assistants[-1].get("session_id"), "sess-recover")


if __name__ == "__main__":
    unittest.main()
