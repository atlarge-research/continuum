"""Regression tests for benchmark publisher source contracts."""

import ast
from pathlib import Path
import unittest


class PublisherCompletionLoopTests(unittest.TestCase):
    def assert_waits_until_at_least_target(self, source_path, received_name, target_name):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        comparisons = [
            node.test
            for node in ast.walk(tree)
            if isinstance(node, ast.While) and isinstance(node.test, ast.Compare)
        ]

        matching_less_than = [
            comparison
            for comparison in comparisons
            if (
                isinstance(comparison.left, ast.Name)
                and comparison.left.id == received_name
                and len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.Lt)
                and len(comparison.comparators) == 1
                and isinstance(comparison.comparators[0], ast.Name)
                and comparison.comparators[0].id == target_name
            )
        ]
        exact_waits = [
            comparison
            for comparison in comparisons
            if (
                isinstance(comparison.left, ast.Name)
                and comparison.left.id == received_name
                and len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.NotEq)
                and len(comparison.comparators) == 1
                and isinstance(comparison.comparators[0], ast.Name)
                and comparison.comparators[0].id == target_name
            )
        ]

        self.assertEqual(len(matching_less_than), 1)
        self.assertEqual(exact_waits, [])

    def test_image_classification_publisher_accepts_extra_responses(self):
        repo_root = Path(__file__).resolve().parents[3]
        source_path = (
            repo_root
            / "application/image_classification/src/publisher/src/publisher.py"
        )

        self.assert_waits_until_at_least_target(source_path, "RECEIVED", "MAX_IMGS")

    def test_text_translation_publisher_accepts_extra_responses(self):
        repo_root = Path(__file__).resolve().parents[3]
        source_path = repo_root / "application/text_translation/src/publisher/src/publisher.py"

        self.assert_waits_until_at_least_target(source_path, "RECEIVED", "MAX_TXTS")
