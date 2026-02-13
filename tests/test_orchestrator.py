import copy
import unittest
import xml.etree.ElementTree as ET

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


if __name__ == "__main__":
    unittest.main()
