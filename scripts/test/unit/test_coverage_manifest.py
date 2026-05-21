"""Regression tests for the major-function coverage audit manifest."""

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "scripts" / "test" / "coverage_manifest.json"


def _load_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _defined_symbols(source_path: Path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    symbols = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add("%s.%s" % (node.name, child.name))
    return symbols


class CoverageManifestTests(unittest.TestCase):
    def test_manifest_schema_paths_and_scenarios_are_valid(self):
        manifest = _load_manifest()

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["kind"], "ContinuumMajorFunctionCoverageAudit")
        self.assertTrue(manifest["entries"])

        for entry in manifest["entries"]:
            with self.subTest(surface=entry.get("surface")):
                surface = ROOT / entry["surface"]
                self.assertTrue(surface.is_file(), entry["surface"])
                self.assertTrue(entry["functions"])
                self.assertTrue(entry["test_paths"])
                self.assertTrue(entry["success"].strip())
                self.assertTrue(entry["failure"].strip())

                for test_path in entry["test_paths"]:
                    self.assertTrue((ROOT / test_path).is_file(), test_path)

    def test_audited_major_functions_exist(self):
        manifest = _load_manifest()

        for entry in manifest["entries"]:
            surface = ROOT / entry["surface"]
            symbols = _defined_symbols(surface)
            for function_name in entry["functions"]:
                with self.subTest(surface=entry["surface"], function=function_name):
                    self.assertIn(function_name, symbols)

    def test_runtime_and_parser_surfaces_have_unit_coverage(self):
        manifest = _load_manifest()
        e2e_only_prefixes = ("scripts/test/",)

        for entry in manifest["entries"]:
            if entry["surface"].startswith(e2e_only_prefixes):
                continue
            with self.subTest(surface=entry["surface"]):
                self.assertTrue(
                    any(path.startswith("scripts/test/unit/") for path in entry["test_paths"]),
                    "expected at least one unit test path",
                )


if __name__ == "__main__":
    unittest.main()
