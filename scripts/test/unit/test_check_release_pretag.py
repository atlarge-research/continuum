"""Unit tests for the M1 pre-tag readiness checker."""

# pylint: disable=missing-class-docstring,missing-function-docstring,protected-access
# pylint: disable=too-many-public-methods

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.test import check_release_matrix, check_release_pretag


def _valid_cloud_audit_report_text():
    required_gates = "".join(
        "- %s: PASS\n" % (gate,) for gate in check_release_matrix.REQUIRED_CLOUD_AUDIT_GATES
    )
    return (
        "## Required Gates\n"
        + required_gates
        + "\n"
        "## Informational Checks\n"
        "- release evidence artifact audit: OK\n"
        "- M1 pre-tag readiness check: FINDINGS OR UNAVAILABLE (1)\n"
        "\n"
        "## Output Excerpts\n"
        "### docs path reference check\n"
        "TOTAL_MISSING_REFERENCES=0\n"
        "### public release-claims check\n"
        "TOTAL_RELEASE_CLAIM_ISSUES=0\n"
        "### release certification matrix check\n"
        "TOTAL_RELEASE_MATRIX_ISSUES=0\n"
        "### release evidence artifact audit\n"
        "TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0\n"
        "### M1 pre-tag readiness check\n"
        "TOTAL_RELEASE_PRETAG_ISSUES=9\n"
    )


def _valid_cloud_audit_report_text_for(timestamp: str):
    return _valid_cloud_audit_report_text().replace(
        "## Required Gates\n",
        "# Cloud Static Audit Report - %s\n\n## Required Gates\n" % (timestamp,),
        1,
    )


class CheckReleasePretagTests(unittest.TestCase):
    def _write_release_notes(self, root: Path, omitted_command=None, extra_evidence_docs=None):
        commands = [
            command
            for command in check_release_pretag.REQUIRED_PRETAG_COMMANDS
            if command != omitted_command
        ]
        evidence_docs = [
            "docs/release_evidence_m1_2026-05-29.md",
            *(extra_evidence_docs or []),
        ]
        evidence_lines = "\n".join(
            "%d. `%s`" % (index, evidence_doc)
            for index, evidence_doc in enumerate(evidence_docs, start=1)
        )
        notes_text = (
            "# Release Notes\n\n"
            "## 2. Primary Evidence\n\n"
            + evidence_lines
            + "\n\n"
            "## 7. Pre-Tag Gate\n\n"
            "```bash\n"
            + "\n".join(commands)
            + "\n```\n"
        )
        notes_path = root / "docs" / "release_notes_m1_draft.md"
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(notes_text, encoding="utf-8")

    def _write_evidence(
        self,
        root: Path,
        verify_command="sudo -n /usr/local/bin/continuum-hostctl verify",
        verify_result="PASS",
        report_path=None,
        git_commit="abcdef0",
        tree_state="Clean source tree synced to the dedicated runner",
        current_finding=None,
        intro_text="",
    ):
        if report_path is None:
            report_path = (
                root
                / "logs"
                / "cloud_static_audit"
                / "cloud_static_audit_2026-05-24T000000Z.md"
            )
        report_timestamp = report_path.name.removeprefix("cloud_static_audit_").removesuffix(
            ".md"
        )
        if report_timestamp == report_path.name:
            report_timestamp = "2026-05-24T000000Z"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            _valid_cloud_audit_report_text_for(report_timestamp),
            encoding="utf-8",
        )
        evidence_path = root / "docs" / "release_evidence_m1_2026-05-29.md"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        finding_line = (
            "| Current finding | %s |\n" % (current_finding,)
            if current_finding is not None
            else ""
        )
        evidence_path.write_text(
            intro_text
            + (
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Git commit | `%s` |\n"
                "| Tree state | %s |\n"
                "| Report | `%s` |\n"
                "| Required gates | PASS |\n"
                "| Result | `TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0` |\n"
                "| Verify command | `%s` |\n"
                "| Verify result | %s |\n"
                "%s"
                % (
                    git_commit,
                    tree_state,
                    report_path,
                    verify_command,
                    verify_result,
                    finding_line,
                )
            ),
            encoding="utf-8",
        )

    def _write_extra_evidence(self, root: Path, path: str, git_commit="abcdef0"):
        evidence_path = root / path
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            "| Field | Value |\n"
            "| --- | --- |\n"
            "| Git commit | `%s` |\n"
            "| Tree state | Clean source tree synced to the dedicated runner |\n"
            % (git_commit,),
            encoding="utf-8",
        )

    def _find_pretag_issues(self, root: Path, current_commit="abcdef0", status=""):
        with mock.patch.object(
            check_release_pretag,
            "_current_git_commit",
            return_value=current_commit,
        ), mock.patch.object(
            check_release_pretag,
            "_git_status_porcelain",
            return_value=status,
        ), mock.patch.object(
            check_release_pretag,
            "_git_diff_check",
            return_value=(0, ""),
        ):
            return check_release_pretag.find_pretag_issues(root)

    def test_ready_fixture_passes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root)

            self.assertEqual(self._find_pretag_issues(root), [])

    def test_m1_evidence_must_name_cloud_audit_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root)
            evidence_path = root / "docs" / "release_evidence_m1_2026-05-29.md"
            evidence_path.write_text(
                "\n".join(
                    line
                    for line in evidence_path.read_text(encoding="utf-8").splitlines()
                    if not line.startswith("| Report |")
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-evidence-field-missing",
                        "docs/release_evidence_m1_2026-05-29.md missing Report",
                    )
                ],
            )

    def test_required_commands_match_matrix_checker(self):
        self.assertEqual(
            check_release_pretag.REQUIRED_PRETAG_COMMANDS,
            check_release_matrix.REQUIRED_M1_PRE_TAG_COMMANDS,
        )

    def test_extract_paths_ignores_relative_paths(self):
        self.assertEqual(
            check_release_pretag._extract_paths(
                "`logs/cloud_static_audit_2026-05-24T000000Z.md` "
                "`/tmp/cloud_static_audit_2026-05-24T000000Z.md`"
            ),
            ["/tmp/cloud_static_audit_2026-05-24T000000Z.md"],
        )

    def test_missing_pretag_command_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            omitted = "python3 scripts/test/check_release_pretag.py"
            self._write_release_notes(root, omitted_command=omitted)
            self._write_evidence(root)

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-command-missing",
                        "section 7 is missing '%s'" % (omitted,),
                    )
                ],
            )

    def test_missing_vm_wrapper_command_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            omitted = (
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_openfaas_software_parity"
            )
            self._write_release_notes(root, omitted_command=omitted)
            self._write_evidence(root)

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-command-missing",
                        "section 7 is missing '%s'" % (omitted,),
                    )
                ],
            )

    def test_pretag_commands_must_remain_in_documented_order(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root)
            notes_path = root / "docs" / "release_notes_m1_draft.md"
            notes_path.write_text(
                notes_path.read_text(encoding="utf-8").replace(
                    "sudo -n /usr/local/bin/continuum-hostctl verify\n"
                    "sh scripts/test/setup_agent_host.sh verify\n",
                    "sh scripts/test/setup_agent_host.sh verify\n"
                    "sudo -n /usr/local/bin/continuum-hostctl verify\n",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-command-order",
                        "section 7 lists 'sh scripts/test/setup_agent_host.sh verify' "
                        "before 'sudo -n /usr/local/bin/continuum-hostctl verify'; "
                        "keep pre-tag commands in documented order",
                    )
                ],
            )

    def test_pretag_commands_must_not_be_duplicated(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root)
            notes_path = root / "docs" / "release_notes_m1_draft.md"
            duplicate = "python3 scripts/test/check_release_matrix.py"
            notes_path.write_text(
                notes_path.read_text(encoding="utf-8").replace(
                    "%s\n" % (duplicate,),
                    "%s\n%s\n" % (duplicate, duplicate),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-command-duplicate",
                        "section 7 lists '%s' 2 times; keep one canonical "
                        "pre-tag command" % (duplicate,),
                    )
                ],
            )

    def test_host_helper_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root, verify_result="FAIL before VM execution")

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-host-helper-not-ready",
                        "docs/release_evidence_m1_2026-05-29.md Verify result="
                        "'FAIL before VM execution' expected 'PASS'",
                    )
                ],
            )

    def test_host_helper_evidence_must_use_installed_helper_verifier(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(
                root,
                verify_command="sh scripts/test/setup_agent_host.sh verify",
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-host-helper-command-mismatch",
                        "docs/release_evidence_m1_2026-05-29.md Verify command="
                        "'sh scripts/test/setup_agent_host.sh verify' expected "
                        "'sudo -n /usr/local/bin/continuum-hostctl verify'",
                    )
                ],
            )

    def test_failed_host_helper_result_must_not_use_refreshed_wording(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(
                root,
                verify_result="FAIL before VM execution",
                intro_text="Pre-tag status after the helper-contract refresh:\n\n",
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-host-helper-not-ready",
                        "docs/release_evidence_m1_2026-05-29.md Verify result="
                        "'FAIL before VM execution' expected 'PASS'",
                    ),
                    check_release_pretag.PretagIssue(
                        "pretag-host-helper-refresh-wording-stale",
                        "docs/release_evidence_m1_2026-05-29.md says 'after the "
                        "helper-contract refresh' but Verify result is "
                        "'FAIL before VM execution'",
                    ),
                ],
            )

    def test_passing_host_helper_result_must_not_keep_stale_finding(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(
                root,
                verify_result="PASS",
                current_finding=(
                    "Installed /usr/local/bin/continuum-hostctl does not declare "
                    "HOSTCTL_INTERFACE_VERSION"
                ),
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-host-helper-finding-not-cleared",
                        "docs/release_evidence_m1_2026-05-29.md Current finding="
                        "'Installed /usr/local/bin/continuum-hostctl does not declare "
                        "HOSTCTL_INTERFACE_VERSION' must be cleared when Verify "
                        "result is PASS",
                    )
                ],
            )

    def test_missing_evidence_artifact_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            missing_report = (
                root
                / "logs"
                / "cloud_static_audit"
                / "cloud_static_audit_2026-05-24T000000Z.md"
            )
            self._write_release_notes(root)
            self._write_evidence(root, report_path=missing_report)
            missing_report.unlink()

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-evidence-artifact-missing",
                        "docs/release_evidence_m1_2026-05-29.md references missing %s"
                        % (missing_report,),
                    )
                ],
            )

    def test_missing_relative_cloud_audit_report_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root)
            evidence_path = root / "docs" / "release_evidence_m1_2026-05-29.md"
            missing_report = (
                root
                / "logs"
                / "cloud_static_audit"
                / "cloud_static_audit_2026-05-24T000000Z.md"
            )
            original_report_line = "| Report | `%s` |" % (missing_report,)
            evidence_path.write_text(
                evidence_path.read_text(encoding="utf-8").replace(
                    original_report_line,
                    "| Report | "
                    "`logs/cloud_static_audit/cloud_static_audit_2026-05-24T000000Z.md` |",
                ),
                encoding="utf-8",
            )
            missing_report.unlink()

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-evidence-artifact-missing",
                        "docs/release_evidence_m1_2026-05-29.md references missing %s"
                        % (missing_report,),
                    )
                ],
            )

    def test_m1_evidence_report_must_use_canonical_cloud_audit_directory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            report_path = root / "logs" / "cloud_static_audit_2026-05-24T000000Z.md"
            self._write_evidence(root, report_path=report_path)

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-cloud-audit-report-location",
                        "docs/release_evidence_m1_2026-05-29.md Report=%r "
                        "must be under %r"
                        % (
                            str(report_path),
                            str((root / "logs" / "cloud_static_audit").resolve()),
                        ),
                    )
                ],
            )

    def test_m1_evidence_report_must_use_canonical_cloud_audit_filename(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            report_path = root / "logs" / "cloud_static_audit" / "latest.md"
            self._write_evidence(root, report_path=report_path)

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-cloud-audit-report-name",
                        "docs/release_evidence_m1_2026-05-29.md Report=%r "
                        "must use cloud_static_audit_YYYY-MM-DDTHHMMSSZ.md"
                        % (str(report_path),),
                    )
                ],
            )

    def test_m1_evidence_report_must_have_required_cloud_audit_gates(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            report_path = (
                root
                / "logs"
                / "cloud_static_audit"
                / "cloud_static_audit_2026-05-24T000000Z.md"
            )
            self._write_evidence(root, report_path=report_path)
            report_path.write_text(
                "## Required Gates\n"
                "- compile sweep: PASS\n"
                "\n"
                "## Informational Checks\n"
                "- M1 pre-tag readiness check: FINDINGS OR UNAVAILABLE (1)\n"
                "\n"
                "## Output Excerpts\n"
                "### M1 pre-tag readiness check\n"
                "TOTAL_RELEASE_PRETAG_ISSUES=9\n",
                encoding="utf-8",
            )

            self.assertIn(
                check_release_pretag.PretagIssue(
                    "pretag-cloud-audit-evidence-invalid",
                    "cloud-audit-required-gate-missing: %s missing required gate "
                    "git diff whitespace check" % (report_path,),
                ),
                self._find_pretag_issues(root),
            )

    def test_m1_evidence_report_filename_timestamp_must_match_heading(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            report_path = (
                root
                / "logs"
                / "cloud_static_audit"
                / "cloud_static_audit_2026-05-24T000000Z.md"
            )
            self._write_evidence(root, report_path=report_path)
            report_path.write_text(
                _valid_cloud_audit_report_text_for("2026-05-24T001000Z"),
                encoding="utf-8",
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-cloud-audit-report-timestamp-mismatch",
                        "%s filename timestamp 2026-05-24T000000Z does not match "
                        "heading timestamp 2026-05-24T001000Z" % (report_path,),
                    )
                ],
            )

    def test_m1_evidence_report_must_have_cloud_audit_heading(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            report_path = (
                root
                / "logs"
                / "cloud_static_audit"
                / "cloud_static_audit_2026-05-24T000000Z.md"
            )
            self._write_evidence(root, report_path=report_path)
            report_path.write_text(_valid_cloud_audit_report_text(), encoding="utf-8")

            self.assertIn(
                check_release_pretag.PretagIssue(
                    "pretag-cloud-audit-report-heading-missing",
                    "%s missing '# Cloud Static Audit Report - <timestamp>' heading"
                    % (report_path,),
                ),
                self._find_pretag_issues(root),
            )

    def test_m1_evidence_latest_cloud_audit_report_is_accepted(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            report_dir = root / "logs" / "cloud_static_audit"
            report_dir.mkdir(parents=True)
            old_report = report_dir / "cloud_static_audit_2026-05-24T000000Z.md"
            latest_report = report_dir / "cloud_static_audit_2026-05-24T001000Z.md"
            latest_report.write_text(_valid_cloud_audit_report_text(), encoding="utf-8")
            self._write_evidence(root, report_path=old_report)
            self._write_evidence(root, report_path=latest_report)

            self.assertEqual(self._find_pretag_issues(root), [])

    def test_m1_evidence_must_reference_latest_cloud_audit_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            report_dir = root / "logs" / "cloud_static_audit"
            report_dir.mkdir(parents=True)
            old_report = report_dir / "cloud_static_audit_2026-05-24T000000Z.md"
            latest_report = report_dir / "cloud_static_audit_2026-05-24T001000Z.md"
            latest_report.write_text(_valid_cloud_audit_report_text(), encoding="utf-8")
            self._write_evidence(root, report_path=old_report)

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-cloud-audit-report-not-latest",
                        "docs/release_evidence_m1_2026-05-29.md Report=%r but "
                        "latest cloud audit report is %r"
                        % (str(old_report.resolve()), str(latest_report.resolve())),
                    )
                ],
            )

    def test_evidence_commit_must_match_current_head(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root, git_commit="abcdef0")

            self.assertEqual(
                self._find_pretag_issues(root, current_commit="1234567"),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-source-commit-mismatch",
                        "docs/release_evidence_m1_2026-05-29.md Git commit='abcdef0' "
                        "expected current HEAD '1234567'",
                    )
                ],
            )

    def test_evidence_commit_may_precede_release_doc_only_head(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root, git_commit="abcdef0")

            with mock.patch.object(
                check_release_pretag,
                "_changed_paths_between_commits",
                return_value=[
                    "docs/release_evidence_m1_2026-05-29.md",
                    "docs/release_notes_m1_draft.md",
                    "scripts/test/check_release_pretag.py",
                    "scripts/test/unit/test_check_release_pretag.py",
                ],
            ):
                self.assertEqual(
                    self._find_pretag_issues(root, current_commit="1234567"),
                    [],
                )

    def test_evidence_commit_mismatch_reports_runtime_path_changes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root, git_commit="abcdef0")

            with mock.patch.object(
                check_release_pretag,
                "_changed_paths_between_commits",
                return_value=[
                    "docs/release_evidence_m1_2026-05-29.md",
                    "infrastructure/qemu/qemu.py",
                    "configs/experiments/smoke/infra_one_vm.yaml",
                ],
            ):
                self.assertEqual(
                    self._find_pretag_issues(root, current_commit="1234567"),
                    [
                        check_release_pretag.PretagIssue(
                            "pretag-source-commit-mismatch",
                            "docs/release_evidence_m1_2026-05-29.md Git commit="
                            "'abcdef0' differs from current HEAD '1234567'; "
                            "runtime-affecting paths changed since evidence commit: "
                            "infrastructure/qemu/qemu.py, "
                            "configs/experiments/smoke/infra_one_vm.yaml",
                        )
                    ],
                )

    def test_release_notes_evidence_docs_must_match_current_head(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            extra_doc = "docs/release_evidence_extra_2026-05-23.md"
            self._write_release_notes(root, extra_evidence_docs=[extra_doc])
            self._write_evidence(root)
            self._write_extra_evidence(root, extra_doc, git_commit="1234567")

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-source-commit-mismatch",
                        "%s Git commit='1234567' expected current HEAD 'abcdef0'"
                        % (extra_doc,),
                    )
                ],
            )

    def test_evidence_tree_state_must_be_clean(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(
                root,
                tree_state="Dirty working tree synced intentionally to the dedicated runner",
            )

            self.assertEqual(
                self._find_pretag_issues(root),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-evidence-tree-not-clean",
                        "docs/release_evidence_m1_2026-05-29.md Tree state='Dirty "
                        "working tree synced intentionally to the dedicated runner'; "
                        "release-tag evidence must come from a clean source tree",
                    )
                ],
            )

    def test_current_worktree_must_be_clean(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root)

            self.assertEqual(
                self._find_pretag_issues(root, status=" M file.py\n?? new_file.py"),
                [
                    check_release_pretag.PretagIssue(
                        "pretag-source-tree-dirty",
                        "git status --porcelain reports 2 changed paths "
                        "(modified=1, untracked=1); sample paths: file.py, new_file.py; "
                        "release tag requires a clean worktree",
                    )
                ],
            )

    def test_current_worktree_dirty_summary_categorizes_statuses(self):
        status = (
            " M docs/example.md\n"
            "A  scripts/new_check.py\n"
            " D stale.txt\n"
            "R  old_name.py -> new_name.py\n"
            "?? configs/new.yaml\n"
            "UU conflicted.py\n"
        )

        self.assertEqual(
            check_release_pretag._git_status_dirty_detail(status, path_limit=3),
            "git status --porcelain reports 6 changed paths "
            "(unmerged=1, modified=1, added=1, deleted=1, renamed=1, untracked=1); "
            "sample paths: docs/example.md, scripts/new_check.py, stale.txt; "
            "release tag requires a clean worktree",
        )

    def test_git_status_porcelain_preserves_leading_status_space(self):
        completed = mock.Mock(returncode=0, stdout=" M README.md\n?? new_file.py\n")

        with mock.patch.object(
            check_release_pretag.subprocess,
            "run",
            return_value=completed,
        ):
            self.assertEqual(
                check_release_pretag._git_status_porcelain(Path("/repo")),
                " M README.md\n?? new_file.py",
            )

    def test_git_diff_check_must_pass(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_release_notes(root)
            self._write_evidence(root)

            with mock.patch.object(
                check_release_pretag,
                "_current_git_commit",
                return_value="abcdef0",
            ), mock.patch.object(
                check_release_pretag,
                "_git_status_porcelain",
                return_value="",
            ), mock.patch.object(
                check_release_pretag,
                "_git_diff_check",
                return_value=(2, "docs/example.md:12: trailing whitespace"),
            ):
                self.assertEqual(
                    check_release_pretag.find_pretag_issues(root),
                    [
                        check_release_pretag.PretagIssue(
                            "pretag-diff-check-failed",
                            "git diff --check failed: docs/example.md:12: trailing whitespace",
                        )
                    ],
                )


if __name__ == "__main__":
    unittest.main()
