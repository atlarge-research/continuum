"""Unit tests for the docs path reference checker."""

import tempfile
import unittest
from pathlib import Path

from scripts.test import check_docs_paths


class CheckDocsPathsTests(unittest.TestCase):
    def _write_doc(self, root: Path, name: str, text: str):
        docs = root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / name).write_text(text, encoding="utf-8")

    def test_existing_repo_shaped_reference_passes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "configs").mkdir()
            (root / "configs" / "example.yaml").write_text("kind: test\n", encoding="utf-8")
            self._write_doc(root, "guide.md", "Use `configs/example.yaml`.")

            self.assertEqual(check_docs_paths.find_missing_references(root), [])

    def test_missing_repo_shaped_reference_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_doc(root, "guide.md", "Use `configs/missing.yaml`.")

            self.assertEqual(
                check_docs_paths.find_missing_references(root),
                [check_docs_paths.MissingReference("docs/guide.md", "configs/missing.yaml")],
            )

    def test_bare_names_are_ignored(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_doc(
                root,
                "guide.md",
                "Ignore `.yaml`, `metadata.json`, and `runtime_config.py`.",
            )

            self.assertEqual(check_docs_paths.find_missing_references(root), [])

    def test_planned_test_layout_paths_are_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_doc(
                root,
                "guide.md",
                "Future layout: `scripts/test/unit/` and `scripts/test/e2e/`.",
            )

            self.assertEqual(check_docs_paths.find_missing_references(root), [])

    def test_fenced_code_blocks_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_doc(
                root,
                "guide.md",
                "```text\n`configs/generated.yaml`\n```\n",
            )

            self.assertEqual(check_docs_paths.find_missing_references(root), [])

    def test_line_and_anchor_suffixes_resolve_to_existing_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "input").mkdir()
            (root / "input" / "input.py").write_text("# test\n", encoding="utf-8")
            self._write_doc(
                root,
                "guide.md",
                "See `input/input.py:12` and `input/input.py#details`.",
            )

            self.assertEqual(check_docs_paths.find_missing_references(root), [])


if __name__ == "__main__":
    unittest.main()
