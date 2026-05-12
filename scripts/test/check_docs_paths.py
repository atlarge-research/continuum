#!/usr/bin/env python3
"""Check documentation references to repo-local paths."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[2]
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

KNOWN_PATH_PREFIXES = (
    "application/",
    "configs/",
    "configuration/",
    "docs/",
    "execution_model/",
    "infrastructure/",
    "input/",
    "playbooks/",
    "resource_manager/",
    "roles/",
    "scripts/",
    "sysconfig/",
)
KNOWN_ROOT_PATHS = (
    ".ansible-lint",
    "README.md",
    "ansible.cfg",
    "continuum.py",
    "requirements.txt",
)
PLANNED_PATHS = (
    "scripts/test/e2e/",
    "scripts/test/e2e",
    "scripts/test/unit/",
    "scripts/test/unit",
)


@dataclass(frozen=True)
class MissingReference:
    """A missing repo-local path reference found in a docs file."""

    doc_path: str
    reference: str


def strip_fenced_code_blocks(text: str) -> str:
    """Remove fenced code blocks before scanning inline-code references."""
    kept_lines = []
    in_fence = False
    fence_marker = ""

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if not in_fence:
            kept_lines.append(line)

    return "\n".join(kept_lines)


def normalize_reference(token: str) -> str:
    """Return a normalized candidate path, or an empty string for non-path tokens."""
    reference = token.strip().strip(".,;)")
    if not reference:
        return ""
    if reference.startswith(("http://", "https://", "/", "~")):
        return ""
    if any(char.isspace() for char in reference):
        return ""
    if any(char in reference for char in "<>|*$"):
        return ""

    while reference.startswith("./"):
        reference = reference[2:]

    reference = reference.split("#", 1)[0]
    reference = reference.split(":", 1)[0]
    if not reference or ".." in Path(reference).parts:
        return ""

    if reference.startswith(KNOWN_PATH_PREFIXES) or reference in KNOWN_ROOT_PATHS:
        return reference
    return ""


def iter_doc_references(doc_path: Path) -> Iterable[str]:
    """Yield normalized repo-local path references from a Markdown document."""
    text = doc_path.read_text(encoding="utf-8", errors="ignore")
    text = strip_fenced_code_blocks(text)
    for token in INLINE_CODE_RE.findall(text):
        reference = normalize_reference(token)
        if reference:
            yield reference


def find_missing_references(root: Path = ROOT) -> List[MissingReference]:
    """Return missing repo-local path references from Markdown docs under root/docs."""
    root = root.resolve()
    missing = []
    for doc_path in sorted((root / "docs").glob("*.md")):
        rel_doc = doc_path.relative_to(root).as_posix()
        for reference in sorted(set(iter_doc_references(doc_path))):
            if reference in PLANNED_PATHS:
                continue
            if not (root / reference).exists():
                missing.append(MissingReference(rel_doc, reference))
    return missing


def main() -> int:
    """Run the docs path reference check."""
    missing = find_missing_references(ROOT)
    for item in missing:
        print("%s: %s" % (item.doc_path, item.reference))
    print("TOTAL_MISSING_REFERENCES=%d" % (len(missing)))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
