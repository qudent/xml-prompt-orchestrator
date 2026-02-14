"""XML tree operations and git annotation helpers."""

from __future__ import annotations

import hashlib
import subprocess
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Optional

from .constants import ASSISTANT_TAG, BRANCH_TAG, HUMAN_TAG


def new_short_id() -> str:
    return uuid.uuid4().hex[:8]


def find_message_by_id(root: ET.Element, message_id: str) -> Optional[ET.Element]:
    for node in root.iter():
        if node.get("id") == message_id:
            return node
    return None


def parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _siblings(parent: ET.Element, node: ET.Element) -> list[ET.Element]:
    return list(parent)


def _node_index(parent: ET.Element, node: ET.Element) -> int:
    for idx, child in enumerate(list(parent)):
        if child is node:
            return idx
    raise ValueError("node not found in parent")


def insert_after(parent: ET.Element, node: ET.Element, new_node: ET.Element) -> None:
    idx = _node_index(parent, node)
    parent.insert(idx + 1, new_node)


def human_text(node: ET.Element) -> str:
    return (node.text or "").strip()


def has_following_assistant(parent: ET.Element, human: ET.Element) -> bool:
    siblings = _siblings(parent, human)
    idx = _node_index(parent, human)
    for sibling in siblings[idx + 1 :]:
        if sibling.tag == ASSISTANT_TAG:
            return True
        if sibling.tag == HUMAN_TAG:
            return False
    return False


def previous_assistant_session(parent: ET.Element, human: ET.Element) -> Optional[str]:
    siblings = _siblings(parent, human)
    idx = _node_index(parent, human)
    for sibling in reversed(siblings[:idx]):
        if sibling.tag != ASSISTANT_TAG:
            continue
        session_id = sibling.get("session_id")
        if session_id:
            return session_id
    return None


def _container_nodes(root: ET.Element) -> list[ET.Element]:
    nodes: list[ET.Element] = []
    for node in root.iter():
        if node.tag in ("conversation", BRANCH_TAG):
            nodes.append(node)
    return nodes


def normalize_free_text_humans(root: ET.Element) -> int:
    """
    Convert bare text nodes in conversation/branch containers into <human> nodes.

    This lets users type plain text anywhere between XML elements and have it
    normalized into explicit human messages at the same structural position.
    """
    changed = 0
    for parent in _container_nodes(root):
        initial_text = (parent.text or "").strip()
        if initial_text:
            new_human = ET.Element(HUMAN_TAG)
            new_human.text = initial_text
            parent.insert(0, new_human)
            changed += 1
        parent.text = None

        for child in list(parent):
            tail_text = (child.tail or "").strip()
            child.tail = None
            if not tail_text:
                continue
            new_human = ET.Element(HUMAN_TAG)
            new_human.text = tail_text
            insert_after(parent, child, new_human)
            changed += 1
    return changed


def _previous_human_id(parent: ET.Element, human: ET.Element) -> Optional[str]:
    siblings = _siblings(parent, human)
    idx = _node_index(parent, human)
    for sibling in reversed(siblings[:idx]):
        if sibling.tag != HUMAN_TAG:
            continue
        message_id = sibling.get("id")
        if message_id:
            return message_id
    return None


def _has_following_messages(parent: ET.Element, human: ET.Element) -> bool:
    siblings = _siblings(parent, human)
    idx = _node_index(parent, human)
    return bool(siblings[idx + 1 :])


def _human_sequence_signatures(root: ET.Element) -> list[tuple[ET.Element, str]]:
    text_counts: dict[str, int] = {}
    signatures: list[tuple[ET.Element, str]] = []
    for human in root.iter(HUMAN_TAG):
        message_id = human.get("id")
        if message_id:
            signature = f"id:{message_id}"
        else:
            digest = hashlib.sha1(human_text(human).encode("utf-8")).hexdigest()[:16]
            text_counts[digest] = text_counts.get(digest, 0) + 1
            signature = f"text:{digest}:{text_counts[digest]}"
        signatures.append((human, signature))
    return signatures


def fork_new_middle_humans(current_root: ET.Element, previous_root: Optional[ET.Element]) -> int:
    """
    Fork newly inserted middle humans that would otherwise overwrite timeline order.
    """
    if previous_root is None:
        return 0

    previous_counts = Counter(signature for _, signature in _human_sequence_signatures(previous_root))
    changed = 0
    parents = parent_map(current_root)
    for human, signature in _human_sequence_signatures(current_root):
        if previous_counts[signature] > 0:
            previous_counts[signature] -= 1
            continue

        parent = parents.get(human)
        if parent is None:
            continue
        if parent.tag == BRANCH_TAG:
            continue
        if not _has_following_messages(parent, human):
            continue

        branch_attrs = {"id": new_short_id()}
        from_id = _previous_human_id(parent, human)
        if from_id:
            branch_attrs["from"] = from_id
        branch = ET.Element(BRANCH_TAG, branch_attrs)

        if human.get("id") is None:
            human.set("id", new_short_id())
        if human.get("resume_from") is None:
            resume_from = previous_assistant_session(parent, human)
            if resume_from:
                human.set("resume_from", resume_from)

        idx = _node_index(parent, human)
        parent.remove(human)
        branch.append(human)
        parent.insert(idx, branch)
        changed += 1
    return changed


def apply_middle_edit_forks(current_root: ET.Element, previous_root: Optional[ET.Element]) -> int:
    if previous_root is None:
        return 0

    previous_text_by_id = {
        node.get("id"): human_text(node)
        for node in previous_root.iter(HUMAN_TAG)
        if node.get("id")
    }
    changed = 0
    parents = parent_map(current_root)

    for human in list(current_root.iter(HUMAN_TAG)):
        message_id = human.get("id")
        if not message_id or message_id not in previous_text_by_id:
            continue

        current_text = human_text(human)
        old_text = previous_text_by_id[message_id]
        if current_text == old_text:
            continue

        parent = parents.get(human)
        if parent is None:
            continue
        if not has_following_assistant(parent, human):
            continue

        # Preserve old branch by restoring original message text.
        human.text = old_text
        branch = ET.Element(BRANCH_TAG, {"id": new_short_id(), "from": message_id})
        fork_human = ET.Element(HUMAN_TAG, {"id": new_short_id(), "forked_from": message_id})
        fork_human.text = current_text
        resume_from = previous_assistant_session(parent, human)
        if resume_from:
            fork_human.set("resume_from", resume_from)
        branch.append(fork_human)
        insert_after(parent, human, branch)
        changed += 1

    return changed


def find_pending_human(root: ET.Element) -> Optional[ET.Element]:
    parents = parent_map(root)
    for human in root.iter(HUMAN_TAG):
        if (human.get("killed", "")).lower() == "true":
            continue
        if (human.get("running", "")).lower() == "true":
            continue
        parent = parents.get(human)
        if parent is None:
            continue
        if has_following_assistant(parent, human):
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


def insert_assistant_after_human(
    root: ET.Element,
    human_id: str,
    *,
    text: str,
    status: str,
    session_id: Optional[str],
    log_path_value: str,
) -> bool:
    target = find_message_by_id(root, human_id)
    if target is None:
        return False

    parent = parent_map(root).get(target)
    if parent is None:
        return False

    assistant = ET.Element(ASSISTANT_TAG, {"id": new_short_id(), "status": status})
    assistant.text = text
    if session_id:
        assistant.set("session_id", session_id)
    assistant.set("log_path", log_path_value)
    insert_after(parent, target, assistant)
    return True
