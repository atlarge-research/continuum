"""Regression tests for the cloud static audit script."""

# pylint: disable=missing-class-docstring,missing-function-docstring

import json
import re
import unittest
from pathlib import Path

from scripts.test import check_release_matrix


class CloudStaticAuditScriptTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[3]
        self.audit_script = self.repo_root / "scripts/test/run_cloud_static_audit.sh"

    def test_release_readiness_checks_are_informational(self):
        script_text = self.audit_script.read_text(encoding="utf-8")

        self.assertIn(
            'run_capture release_evidence_artifacts "release evidence artifact audit" optional',
            script_text,
        )
        self.assertIn(
            '"$PYTHON" -B scripts/test/check_release_evidence_artifacts.py',
            script_text,
        )
        self.assertIn(
            'run_capture release_pretag "M1 pre-tag readiness check" optional',
            script_text,
        )
        self.assertIn(
            '"$PYTHON" -B scripts/test/check_release_pretag.py',
            script_text,
        )
        self.assertNotIn(
            'run_capture release_evidence_artifacts "release evidence artifact audit" required',
            script_text,
        )
        self.assertNotIn(
            'run_capture release_pretag "M1 pre-tag readiness check" required',
            script_text,
        )

    def test_shell_wrapper_syntax_checks_are_required_gates(self):
        script_text = self.audit_script.read_text(encoding="utf-8")

        self.assertIn(
            'run_capture shell_syntax_audit "cloud audit shell syntax check" required',
            script_text,
        )
        self.assertIn(
            'run_capture shell_syntax_smoke "smoke wrapper shell syntax check" required',
            script_text,
        )
        self.assertIn(
            'run_capture shell_syntax_host_setup "host setup shell syntax check" required',
            script_text,
        )
        self.assertIn("bash -n scripts/test/run_cloud_static_audit.sh", script_text)
        self.assertIn("sh -n scripts/test/run_smoke_host.sh", script_text)
        self.assertIn("sh -n scripts/test/setup_agent_host.sh", script_text)

    def test_required_gate_titles_match_release_matrix_contract(self):
        script_text = self.audit_script.read_text(encoding="utf-8")

        gate_titles = tuple(
            re.findall(r'^run_capture\s+\S+\s+"([^"]+)"\s+required', script_text, re.MULTILINE)
        )

        self.assertEqual(gate_titles, check_release_matrix.REQUIRED_CLOUD_AUDIT_GATES)

    def test_all_parity_suites_have_cloud_safe_prereq_checks(self):
        script_text = self.audit_script.read_text(encoding="utf-8")
        test_config_path = self.repo_root / "scripts/test/test_config.json"
        test_config = json.loads(test_config_path.read_text(encoding="utf-8"))
        parity_suites = sorted(
            suite_name
            for suite_name, suite_config in test_config["test_suites"].items()
            if any(
                directory.startswith("configs/experiments/parity/")
                for directory in suite_config.get("directories", [])
            )
        )

        for suite_name in parity_suites:
            has_runner_check = "--check-prereqs --suite %s" % (suite_name,) in script_text
            has_cache_check = (
                "prime_local_registry_cache.py" in script_text
                and "--suite %s" % (suite_name,) in script_text
                and "--check-only" in script_text
            )
            self.assertTrue(
                has_runner_check or has_cache_check,
                msg="%s should have an optional cloud-safe prerequisite check" % (suite_name,),
            )


if __name__ == "__main__":
    unittest.main()
