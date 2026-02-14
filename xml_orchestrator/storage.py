"""Filesystem and XML serialization utilities."""

from __future__ import annotations

import copy
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


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
