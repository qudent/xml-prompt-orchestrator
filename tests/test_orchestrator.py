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


def init_git_repo(repo: Path) -> None:
    py_subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
    py_subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True
    )
    py_subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True
    )


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

            init_git_repo(repo)
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

            init_git_repo(repo)
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

    def test_start_defers_id_write_until_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            original_text = (
                "<conversation backend=\"codex\">\n"
                "  <human>Question A</human>\n"
                "</conversation>\n"
            )
            conversation = repo / "orchestration.xml"
            conversation.write_text(original_text, encoding="utf-8")

            init_git_repo(repo)
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
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                loop.tick()
                self.assertIsNotNone(loop.active_run)

            current = conversation.read_text(encoding="utf-8")
            # One-go semantics: no id/running marker write before assistant completion.
            self.assertEqual(current, original_text)

    def test_diff_save_launches_parallel_runs_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            conversation = repo / "orchestration.xml"
            conversation.write_text(
                (
                    "<conversation backend=\"codex\">\n"
                    "  <human>Q1</human>\n"
                    "</conversation>\n"
                ),
                encoding="utf-8",
            )

            init_git_repo(repo)
            py_subprocess.run(["git", "add", "orchestration.xml"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            loop = orchestrator.WatchLoop(
                conversation_file=conversation,
                repo_path=repo,
                poll_seconds=0.01,
                use_inotify=False,
            )

            real_run = py_subprocess.run
            new_sessions: list[str] = []

            def fake_run(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "tmux":
                    if len(cmd) > 1 and cmd[1] == "new-session":
                        session_name = cmd[4]
                        new_sessions.append(session_name)
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                # First save launches one run for Q1.
                loop.tick()
                self.assertEqual(len(new_sessions), 1)
                self.assertEqual(len(loop.active_runs), 1)

                # New save adds Q2; should launch a second run without relaunching Q1.
                conversation.write_text(
                    (
                        "<conversation backend=\"codex\">\n"
                        "  <human>Q1</human>\n"
                        "  <human>Q2</human>\n"
                        "</conversation>\n"
                    ),
                    encoding="utf-8",
                )
                loop.tick()
                self.assertEqual(len(new_sessions), 2)
                self.assertEqual(len(loop.active_runs), 2)

                # Pure re-save (no content diff) should not spawn new runs.
                same_text = conversation.read_text(encoding="utf-8")
                conversation.write_text(same_text, encoding="utf-8")
                loop.tick()
                self.assertEqual(len(new_sessions), 2)
                self.assertEqual(len(loop.active_runs), 2)

    def test_parallel_second_run_does_not_resume_first_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            conversation = repo / "orchestration.xml"
            conversation.write_text(
                (
                    "<conversation backend=\"codex\">\n"
                    "  <human id=\"seed\">Seed</human>\n"
                    "  <assistant id=\"a0\" session_id=\"sess-base\">Base</assistant>\n"
                    "  <human>Q1</human>\n"
                    "</conversation>\n"
                ),
                encoding="utf-8",
            )

            init_git_repo(repo)
            py_subprocess.run(["git", "add", "orchestration.xml"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            loop = orchestrator.WatchLoop(
                conversation_file=conversation,
                repo_path=repo,
                poll_seconds=0.01,
                use_inotify=False,
            )

            real_run = py_subprocess.run
            new_session_cmds: list[str] = []

            def fake_run(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "tmux":
                    if len(cmd) > 1 and cmd[1] == "new-session":
                        new_session_cmds.append(cmd[-1])
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                loop.tick()
                self.assertEqual(len(new_session_cmds), 1)
                self.assertIn("resume sess-base", new_session_cmds[0])

                conversation.write_text(
                    (
                        "<conversation backend=\"codex\">\n"
                        "  <human id=\"seed\">Seed</human>\n"
                        "  <assistant id=\"a0\" session_id=\"sess-base\">Base</assistant>\n"
                        "  <human>Q1</human>\n"
                        "  <human>Q2</human>\n"
                        "</conversation>\n"
                    ),
                    encoding="utf-8",
                )
                loop.tick()
                self.assertEqual(len(new_session_cmds), 2)
                self.assertNotIn(" resume ", new_session_cmds[1])

    def test_plain_text_between_nodes_autowraps_and_forks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            conversation = repo / "orchestration.xml"
            conversation.write_text(
                (
                    "<conversation backend=\"codex\">\n"
                    "  <human id=\"h1\">Q1</human>\n"
                    "  <assistant id=\"a1\" session_id=\"sess-1\">A1</assistant>\n"
                    "  <human id=\"h2\">Q2</human>\n"
                    "  <assistant id=\"a2\">A2</assistant>\n"
                    "</conversation>\n"
                ),
                encoding="utf-8",
            )

            init_git_repo(repo)
            py_subprocess.run(["git", "add", "orchestration.xml"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            loop = orchestrator.WatchLoop(
                conversation_file=conversation,
                repo_path=repo,
                poll_seconds=0.01,
                use_inotify=False,
            )

            # establish baseline
            loop.previous_root = ET.parse(conversation).getroot()
            loop.last_mtime = conversation.stat().st_mtime

            conversation.write_text(
                (
                    "<conversation backend=\"codex\">\n"
                    "  <human id=\"h1\">Q1</human>\n"
                    "  <assistant id=\"a1\" session_id=\"sess-1\">A1</assistant>\n"
                    "  plain middle question\n"
                    "  <human id=\"h2\">Q2</human>\n"
                    "  <assistant id=\"a2\">A2</assistant>\n"
                    "  plain bottom question\n"
                    "</conversation>\n"
                ),
                encoding="utf-8",
            )

            real_run = py_subprocess.run
            new_session_cmds: list[str] = []

            def fake_run(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "tmux":
                    if len(cmd) > 1 and cmd[1] == "new-session":
                        new_session_cmds.append(cmd[-1])
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                loop.tick()

            root = ET.parse(conversation).getroot()
            branches = list(root.findall("branch"))
            self.assertEqual(len(branches), 1)
            branch_human = branches[0].find("human")
            self.assertIsNotNone(branch_human)
            self.assertEqual((branch_human.text or "").strip(), "plain middle question")
            self.assertEqual(branch_human.get("resume_from"), "sess-1")
            self.assertIn("resume sess-1", new_session_cmds[0])

            top_human_texts = [(node.text or "").strip() for node in root.findall("human")]
            self.assertIn("plain bottom question", top_human_texts)
            self.assertNotIn("plain middle question", top_human_texts)

    def test_plain_text_bottom_append_second_save_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            conversation = repo / "orchestration.xml"
            conversation.write_text(
                (
                    "<conversation backend=\"codex\">\n"
                    "  <human id=\"seed\">Seed</human>\n"
                    "  <assistant id=\"a0\" session_id=\"sess-base\">Base</assistant>\n"
                    "</conversation>\n"
                ),
                encoding="utf-8",
            )

            init_git_repo(repo)
            py_subprocess.run(["git", "add", "orchestration.xml"], cwd=repo, check=True, capture_output=True, text=True)
            py_subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            loop = orchestrator.WatchLoop(
                conversation_file=conversation,
                repo_path=repo,
                poll_seconds=0.01,
                use_inotify=False,
            )

            # establish baseline
            loop.previous_root = ET.parse(conversation).getroot()
            loop.last_mtime = conversation.stat().st_mtime

            real_run = py_subprocess.run
            new_session_cmds: list[str] = []

            def fake_run(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "tmux":
                    if len(cmd) > 1 and cmd[1] == "new-session":
                        new_session_cmds.append(cmd[-1])
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                conversation.write_text(
                    (
                        "<conversation backend=\"codex\">\n"
                        "  <human id=\"seed\">Seed</human>\n"
                        "  <assistant id=\"a0\" session_id=\"sess-base\">Base</assistant>\n"
                        "  first plain question\n"
                        "</conversation>\n"
                    ),
                    encoding="utf-8",
                )
                loop.tick()
                self.assertEqual(len(new_session_cmds), 1)
                self.assertIn("resume sess-base", new_session_cmds[0])

                conversation.write_text(
                    (
                        "<conversation backend=\"codex\">\n"
                        "  <human id=\"seed\">Seed</human>\n"
                        "  <assistant id=\"a0\" session_id=\"sess-base\">Base</assistant>\n"
                        "  <human>first plain question</human>\n"
                        "  second plain question\n"
                        "</conversation>\n"
                    ),
                    encoding="utf-8",
                )
                loop.tick()
                self.assertEqual(len(new_session_cmds), 2)
                self.assertNotIn(" resume ", new_session_cmds[1])

            root = ET.parse(conversation).getroot()
            self.assertEqual(len(root.findall("branch")), 0)
            top_human_texts = [(node.text or "").strip() for node in root.findall("human")]
            self.assertIn("first plain question", top_human_texts)
            self.assertIn("second plain question", top_human_texts)

    def test_malformed_xml_recovers_into_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            conversation = repo / "orchestration.xml"
            conversation.write_text("just typed a question", encoding="utf-8")

            init_git_repo(repo)

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
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "has-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                    if len(cmd) > 1 and cmd[1] == "kill-session":
                        return py_subprocess.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, *args, **kwargs)

            with mock.patch("orchestrator.subprocess.run", side_effect=fake_run):
                loop.tick()

            current = conversation.read_text(encoding="utf-8")
            self.assertIn("<conversation", current)
            self.assertIn("<human", current)
            self.assertIn("just typed a question", current)


if __name__ == "__main__":
    unittest.main()
