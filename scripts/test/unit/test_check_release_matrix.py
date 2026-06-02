"""Unit tests for the release certification matrix checker."""

# pylint: disable=missing-class-docstring,missing-function-docstring,too-many-public-methods
# pylint: disable=too-many-lines

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.test import check_release_matrix


class CheckReleaseMatrixTests(unittest.TestCase):
    def _write_repo(self, root: Path, matrix_text: str, release_notes_text=None):
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "release_certification_matrix.md").write_text(
            matrix_text,
            encoding="utf-8",
        )
        (root / "docs" / "release_evidence_example.md").write_text(
            "# evidence\n\nMatrix row ID: `P-QEMU-01`\n",
            encoding="utf-8",
        )
        (root / "configuration" / "tests" / "qemu").mkdir(parents=True)
        (root / "configuration" / "tests" / "qemu" / "01.cfg").write_text(
            "[infrastructure]\n",
            encoding="utf-8",
        )
        parity_dir = root / "configs" / "experiments" / "parity" / "qemu"
        parity_dir.mkdir(parents=True)
        (parity_dir / "01.yaml").write_text(
            "kind: ContinuumExperiment\n",
            encoding="utf-8",
        )
        test_dir = root / "scripts" / "test"
        test_dir.mkdir(parents=True)
        (test_dir / "test_config.json").write_text(
            json.dumps(
                {
                    "test_suites": {
                        "qemu_infra_parity": {
                            "directories": ["configs/experiments/parity/qemu/"]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        if release_notes_text is None:
            release_notes_text = self._passing_release_notes()
        (root / "docs" / "release_notes_m1_draft.md").write_text(
            release_notes_text,
            encoding="utf-8",
        )
        (root / "docs" / "old_main_parity_issue_seed.md").write_text(
            self._passing_empty_parity_backlog(),
            encoding="utf-8",
        )
        (root / "docs" / "post_release_roadmap.md").write_text(
            "# Post Release Roadmap\n",
            encoding="utf-8",
        )
        (root / "docs" / "rework_milestone_release_plan.md").write_text(
            "# Continuum Rework Milestone Release Plan\n",
            encoding="utf-8",
        )
        (root / "docs" / "rework_plan_stack.md").write_text(
            self._passing_plan_stack(),
            encoding="utf-8",
        )

    def _passing_matrix(self):
        return """# Continuum Release Certification Matrix

## 4. Old-Main Provider And Topology Parity

| ID | Legacy Row | Old Public Surface | Related Rework YAML / Profile | Status | Certification Action |
| --- | --- | --- | --- | --- | --- |
| P-QEMU-01 | `configuration/tests/qemu/01.cfg` | QEMU cloud-only infrastructure | `configs/experiments/parity/qemu/01.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_example.md`. Run fresh evidence before claiming support. |

## 5. Module Certification Backlog
"""

    def _passing_release_notes(self):
        return """# Continuum M1 Milestone Release Notes Draft

## 1. Release Type

Intermediate milestone release. It is not a final replacement for old `main`.

## 2. Primary Evidence

1. `docs/release_certification_matrix.md`
2. `docs/release_evidence_example.md`

## 3. What This Milestone Certifies

| Row | Claim |
| --- | --- |
| `P-QEMU-01` | QEMU infrastructure |

## 4. What This Milestone Does Not Certify

Nothing else in this tiny fixture.

## 5. Known Limitations

## 7. Pre-Tag Gate

```bash
scripts/test/run_cloud_static_audit.sh
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit
python3 scripts/test/check_release_pretag.py
python3 scripts/test/check_release_claims.py
python3 scripts/test/check_release_matrix.py
python3 scripts/test/check_docs_paths.py
git diff --check
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl verify
sh scripts/test/setup_agent_host.sh verify
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_local_parity
```
"""

    def _passing_plan_stack(self):
        return """# Continuum Rework Plan Stack

## Planning Authority

1. `docs/rework_milestone_release_plan.md`
   - Release certification, intermediate milestone sequencing, old-main parity gates.
2. `docs/release_certification_matrix.md`
   - Concrete certified/candidate/historical rows.
3. `docs/post_release_roadmap.md`
   - Future-release roadmap after the final parity release.

## Locked Global Decisions

1. Core/module boundary:
   - Continuum core owns planning, validation, selector/scope resolution,
     module contracts, runtime handoff, state, and evidence contracts.
   - Provider/software/application stacks are modules.
   - qemu is a provider module and must not be described as core.
2. Runtime claims require VM-backed or cloud-backed evidence.
3. Intermediate rework milestones may certify smaller module sets before the
   final main replacement.
4. Final main replacement requires old-main parity or explicit deprecation.
"""

    def _parity_backlog(
        self,
        row_id="P-QEMU-01",
        status="ported-unverified",
        seed=None,
        action_snapshot=None,
    ):
        if seed is None:
            seed = "Run full VM-backed evidence before claiming support."
        if action_snapshot is None:
            action_snapshot = (
                "Evidence: `docs/release_evidence_example.md`. "
                "Run fresh evidence before claiming support."
            )
        return """%s

| Row | Current Status | Issue Seed | Matrix Certification Action |
| --- | --- | --- | --- |
| `%s` | `%s` | %s | %s |
""" % (
            self._passing_empty_parity_backlog().rstrip(),
            row_id,
            status,
            seed,
            action_snapshot,
        )

    def _passing_empty_parity_backlog(self):
        return """# Old-Main Parity Issue Seed

No non-ready rows in this fixture.

## Conversion Notes

When converting this seed into issues:

1. keep one issue per matrix row unless multiple rows share the same concrete
   prerequisite,
2. include the row ID in the issue title,
3. copy the certification action from `docs/release_certification_matrix.md`,
4. require fresh VM-backed or cloud-backed evidence before closing a row as
   certified,
5. update the matrix, release notes, and this seed in the same change.
"""

    def test_current_matrix_has_no_drift(self):
        self.assertEqual(check_release_matrix.find_matrix_issues(), [])

    def test_passing_minimal_matrix(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())

            self.assertEqual(check_release_matrix.find_matrix_issues(root), [])

    def test_evidence_template_must_list_checker_enforced_fields(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix() + """
## 6. Evidence Record Template

| Field | Value |
| --- | --- |
| Matrix row ID |  |
| Git commit |  |
| Tree state |  |
| Date |  |
| Runner context |  |
| Command |  |
| Provider / host prerequisites |  |
| Config |  |
| Suite |  |
| Provider profile |  |
| Software profile |  |
| Runtime targets |  |
| Result summary path |  |
| Artifact root |  |
| Limitations |  |
"""
            self._write_repo(root, matrix_text)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "evidence-template-field-missing",
                        "section 6 evidence template is missing 'Required artifacts checked'",
                    )
                ],
            )

    def test_missing_legacy_config_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("configuration/tests/qemu/01.cfg", ""),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "legacy-config-missing",
                        "configuration/tests/qemu/01.cfg",
                    )
                ],
            )

    def test_old_main_legacy_config_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())

            with mock.patch.object(
                check_release_matrix,
                "iter_old_main_legacy_test_configs",
                return_value=["configuration/tests/qemu/02.cfg"],
            ):
                self.assertEqual(
                    check_release_matrix.find_matrix_issues(root),
                    [
                        check_release_matrix.MatrixIssue(
                            "legacy-config-missing",
                            "configuration/tests/qemu/02.cfg",
                        )
                    ],
                )

    def test_old_main_ref_must_exist_in_git_worktree(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())

            with mock.patch.object(
                check_release_matrix,
                "_is_git_work_tree",
                return_value=True,
            ), mock.patch.object(
                check_release_matrix,
                "_old_main_ref_available",
                return_value=False,
            ), mock.patch.object(
                check_release_matrix,
                "iter_old_main_legacy_test_configs",
                return_value=[],
            ):
                self.assertEqual(
                    check_release_matrix.find_matrix_issues(root),
                    [
                        check_release_matrix.MatrixIssue(
                            "old-main-ref-unavailable",
                            "local git ref origin/main is required for old-main parity "
                            "inventory checks",
                        )
                    ],
                )

    def test_unreferenced_parity_yaml_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("configs/experiments/parity/qemu/01.yaml", ""),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-yaml-unreferenced",
                        "configs/experiments/parity/qemu/01.yaml",
                    ),
                    check_release_matrix.MatrixIssue(
                        "certified-row-config-missing",
                        "P-QEMU-01 is certified but names no rework experiment config",
                    ),
                ],
            )

    def test_unreferenced_parity_suite_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`qemu_infra_parity`", "suite omitted"),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-suite-unreferenced",
                        "qemu_infra_parity",
                    ),
                    check_release_matrix.MatrixIssue(
                        "certified-row-suite-missing",
                        "P-QEMU-01 is certified but names no runner suite",
                    ),
                ],
            )

    def test_referenced_config_must_exist(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "configs" / "experiments" / "parity" / "qemu" / "01.yaml").unlink()

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-config-missing",
                        "P-QEMU-01 references missing configs/experiments/parity/qemu/01.yaml",
                    )
                ],
            )

    def test_referenced_suite_must_exist(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps({"test_suites": {}}),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-unknown-suite",
                        "P-QEMU-01 references unknown suite qemu_infra_parity",
                    )
                ],
            )

    def test_referenced_suite_must_cover_a_row_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "configs" / "experiments" / "parity" / "other").mkdir()
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps(
                    {
                        "test_suites": {
                            "qemu_infra_parity": {
                                "directories": ["configs/experiments/parity/other/"]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-suite-config-mismatch",
                        "P-QEMU-01 suite qemu_infra_parity does not cover any "
                        "referenced experiment config",
                    )
                ],
            )

    def test_certified_row_without_evidence_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace(
                    "`docs/release_evidence_example.md`",
                    "no evidence",
                ),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-missing-evidence",
                        "P-QEMU-01 has no evidence doc",
                    )
                ],
            )

    def test_certified_row_evidence_must_name_row(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence for another row\n\nMatrix row ID: `P-QEMU-02`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-evidence-row-missing",
                        "P-QEMU-01 is not named in its evidence doc(s)",
                    )
                ],
            )

    def test_certified_row_evidence_must_name_exact_row(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence for a subset row\n\nMatrix row ID: `P-QEMU-01-SW`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-evidence-row-missing",
                        "P-QEMU-01 is not named in its evidence doc(s)",
                    )
                ],
            )

    def test_core_ready_row_without_evidence_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            required_gates = ", ".join(check_release_matrix.REQUIRED_CLOUD_AUDIT_GATES)
            self._write_repo(
                root,
                self._passing_matrix()
                + "| M1-CORE | Core | `scripts/test/run_cloud_static_audit.sh` | "
                "Required gates pass: %s. | "
                "`core-ready` | Rerun before tag. |\n"
                % (required_gates,),
                release_notes_text=self._passing_release_notes().replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "| `P-QEMU-01` | QEMU infrastructure |\n"
                    "| `M1-CORE` | Structured core |\n",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-missing-evidence",
                        "M1-CORE has no evidence doc",
                    )
                ],
            )

    def test_certified_runtime_row_must_name_rework_config_and_suite(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "\n## 5. Module Certification Backlog",
                "\n| M1-CUSTOM | Custom runtime row | broad runtime scope | "
                "VM-backed evidence exists | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n\n"
                "## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "| `P-QEMU-01` | QEMU infrastructure |\n",
                "| `P-QEMU-01` | QEMU infrastructure |\n"
                "| `M1-CUSTOM` | Custom runtime row |\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\n"
                "Matrix row ID: `P-QEMU-01`\n"
                "Matrix row ID: `M1-CUSTOM`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "certified-row-config-missing",
                        "M1-CUSTOM is certified but names no rework experiment config",
                    ),
                    check_release_matrix.MatrixIssue(
                        "certified-row-suite-missing",
                        "M1-CUSTOM is certified but names no runner suite",
                    ),
                ],
            )

    def test_m1_core_row_must_name_all_required_cloud_audit_gates(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            omitted_gate = "configured suite catalog"
            required_gates = ", ".join(
                gate
                for gate in check_release_matrix.REQUIRED_CLOUD_AUDIT_GATES
                if gate != omitted_gate
            )
            self._write_repo(
                root,
                self._passing_matrix()
                + "| M1-CORE | Core | `scripts/test/run_cloud_static_audit.sh` | "
                "Required gates pass: %s. | "
                "`core-ready` | Evidence: `docs/release_evidence_example.md`. |\n"
                % (required_gates,),
                release_notes_text=self._passing_release_notes().replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "| `P-QEMU-01` | QEMU infrastructure |\n"
                    "| `M1-CORE` | Structured core |\n",
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\nMatrix row ID: `P-QEMU-01`\nMatrix row ID: `M1-CORE`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "m1-core-required-gate-missing",
                        "M1-CORE required evidence does not name configured suite catalog",
                    )
                ],
            )

    def test_release_notes_must_list_ready_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix(),
                release_notes_text=self._passing_release_notes().replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-ready-row-missing",
                        "P-QEMU-01 is ready in the matrix but absent from section 3",
                    )
                ],
            )

    def test_release_notes_must_list_ready_evidence_docs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix(),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-evidence-missing",
                        "docs/release_evidence_example.md is referenced by a ready "
                        "matrix row but absent from section 2",
                    )
                ],
            )

    def test_release_notes_must_list_matrix_as_primary_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix(),
                release_notes_text=self._passing_release_notes().replace(
                    "1. `docs/release_certification_matrix.md`\n",
                    "",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-matrix-evidence-missing",
                        "section 2 must list docs/release_certification_matrix.md "
                        "as primary evidence",
                    )
                ],
            )

    def test_planning_stack_must_reference_release_planning_docs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "docs" / "rework_plan_stack.md").write_text(
                self._passing_plan_stack().replace(
                    "2. `docs/release_certification_matrix.md`\n"
                    "   - Concrete certified/candidate/historical rows.\n",
                    "",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "planning-stack-release-reference-missing",
                        "docs/rework_plan_stack.md must reference "
                        "docs/release_certification_matrix.md",
                    )
                ],
            )

    def test_planning_stack_must_keep_release_boundaries(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "docs" / "rework_plan_stack.md").write_text(
                self._passing_plan_stack()
                .replace("   - qemu is a provider module and must not be described as core.\n", "")
                .replace("2. Runtime claims require VM-backed or cloud-backed evidence.\n", ""),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "planning-stack-release-boundary-missing",
                        "qemu-provider-module: must state that qemu is a provider "
                        "module, not Continuum core",
                    ),
                    check_release_matrix.MatrixIssue(
                        "planning-stack-release-boundary-missing",
                        "runtime-evidence-required: must state that runtime claims "
                        "require VM-backed or cloud-backed evidence",
                    ),
                ],
            )

    def test_release_notes_must_not_claim_unknown_ready_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix(),
                release_notes_text=self._passing_release_notes().replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "| `P-QEMU-01` | QEMU infrastructure |\n"
                    "| `P-QEMU-99` | Unknown row |\n",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-unknown-row-claimed",
                        "P-QEMU-99 is claimed in section 3 but absent from the matrix",
                    )
                ],
            )

    def test_release_notes_must_not_list_unclaimed_evidence_docs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix(),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "2. `docs/release_evidence_example.md`\n"
                    "3. `docs/release_evidence_unclaimed.md`\n",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-unclaimed-evidence-listed",
                        "docs/release_evidence_unclaimed.md is listed in section 2 "
                        "but not referenced by any ready matrix row",
                    )
                ],
            )

    def test_release_notes_must_not_list_nonready_evidence_docs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "\n## 5. Module Certification Backlog",
                "\n| P-QEMU-02 | legacy | surface | no yaml | `ported-unverified` | "
                "Run fresh evidence before claiming support. "
                "Previous note: `docs/release_evidence_unready.md`. |\n\n"
                "## 5. Module Certification Backlog",
            )
            release_notes_text = self._passing_release_notes().replace(
                "2. `docs/release_evidence_example.md`\n",
                "2. `docs/release_evidence_example.md`\n"
                "3. `docs/release_evidence_unready.md`\n",
            ).replace(
                "Nothing else in this tiny fixture.",
                "`P-QEMU-02` remains unclaimed.",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes_text)
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(
                    row_id="P-QEMU-02",
                    action_snapshot=(
                        "Run fresh evidence before claiming support. "
                        "Previous note: `docs/release_evidence_unready.md`."
                    ),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-unclaimed-evidence-listed",
                        "docs/release_evidence_unready.md is listed in section 2 "
                        "but not referenced by any ready matrix row",
                    )
                ],
            )

    def test_release_notes_must_not_claim_unready_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-uncertified-row-claimed",
                        "P-QEMU-01 is claimed in section 3 but matrix status is "
                        "'ported-unverified'",
                    )
                ],
            )

    def test_release_notes_must_list_unready_rows_as_nonclaims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-nonclaim-row-missing",
                        "P-QEMU-01 is not ready in the matrix but absent from section 4",
                    )
                ],
            )

    def test_release_notes_must_not_list_ready_rows_as_nonclaims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix(),
                release_notes_text=self._passing_release_notes().replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-ready-row-nonclaimed",
                        "P-QEMU-01 is ready in the matrix but listed in section 4 "
                        "as unclaimed",
                    )
                ],
            )

    def test_parity_backlog_must_list_nonready_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-nonready-row-missing",
                        "P-QEMU-01 is not ready in the matrix but absent from "
                        "docs/old_main_parity_issue_seed.md",
                    )
                ],
            )

    def test_parity_backlog_must_not_keep_ready_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(status="certified"),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-ready-row-listed",
                        "P-QEMU-01 is ready in the matrix but still listed as future "
                        "work in docs/old_main_parity_issue_seed.md",
                    )
                ],
            )

    def test_parity_backlog_must_keep_issue_conversion_contract(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._passing_empty_parity_backlog().replace(
                    "2. include the row ID in the issue title,\n",
                    "",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-conversion-note-missing",
                        "row-id-in-title: conversion notes must require the row ID "
                        "in the issue title",
                    )
                ],
            )

    def test_parity_backlog_status_must_match_matrix_status(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(status="historical"),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-status-mismatch",
                        "P-QEMU-01 backlog status 'historical' does not match "
                        "matrix status 'ported-unverified'",
                    )
                ],
            )

    def test_parity_backlog_must_not_list_unknown_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(root, self._passing_matrix())
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(row_id="P-QEMU-99"),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-unknown-row",
                        "P-QEMU-99 is listed in docs/old_main_parity_issue_seed.md "
                        "but absent from the matrix",
                    )
                ],
            )

    def test_parity_backlog_nonready_rows_need_issue_seed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(seed=""),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-empty-issue-seed",
                        "P-QEMU-01 has no actionable issue seed in "
                        "docs/old_main_parity_issue_seed.md",
                    )
                ],
            )

    def test_parity_backlog_issue_seed_needs_closure_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(seed="Investigate whether this still matters."),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-closure-path-missing",
                        "P-QEMU-01 issue seed must require fresh evidence or an explicit "
                        "historical/deprecation disposition",
                    )
                ],
            )

    def test_parity_backlog_must_copy_matrix_action(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(action_snapshot="Run some tests later."),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-action-snapshot-mismatch",
                        "P-QEMU-01 action snapshot does not match matrix "
                        "Certification Action",
                    )
                ],
            )

    def test_parity_backlog_requires_matrix_action_snapshot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`ported-unverified`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(action_snapshot=""),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "parity-backlog-action-snapshot-missing",
                        "P-QEMU-01 must copy the matrix Certification Action into "
                        "docs/old_main_parity_issue_seed.md",
                    )
                ],
            )

    def test_nonready_parity_matrix_action_needs_closure_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace(
                    "`certified` | Evidence: `docs/release_evidence_example.md`. "
                    "Run fresh evidence before claiming support.",
                    "`ported-unverified` | Investigate whether this still matters.",
                ),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ).replace(
                    "| `P-QEMU-01` | QEMU infrastructure |\n",
                    "",
                ).replace(
                    "Nothing else in this tiny fixture.",
                    "`P-QEMU-01` remains unclaimed.",
                ),
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(action_snapshot="Investigate whether this still matters."),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-closure-path-missing",
                        "P-QEMU-01 action must require fresh evidence or an explicit "
                        "historical/deprecation disposition",
                    )
                ],
            )

    def test_release_notes_must_keep_pretag_gate_commands(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix(),
                release_notes_text=self._passing_release_notes().replace(
                    "sudo -n -u continuum-smoke "
                    "/usr/local/bin/run-continuum-smoke release-artifact-audit\n",
                    "",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-pretag-command-missing",
                        "section 7 is missing "
                        "'sudo -n -u continuum-smoke "
                        "/usr/local/bin/run-continuum-smoke release-artifact-audit'",
                    )
                ],
            )

    def test_release_notes_must_state_intermediate_release_type(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            release_notes = self._passing_release_notes().replace(
                "Intermediate milestone release. It is not a final replacement for old `main`.",
                "Release notes for this fixture.",
            )
            self._write_repo(root, self._passing_matrix(), release_notes_text=release_notes)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-type-intermediate-missing",
                        "section 1 must describe M1 as an intermediate milestone or "
                        "pre-release",
                    ),
                    check_release_matrix.MatrixIssue(
                        "release-notes-final-replacement-denial-missing",
                        "section 1 must state that M1 is not a final replacement for "
                        "old main",
                    ),
                ],
            )

    def test_release_notes_must_deny_final_main_replacement(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            release_notes = self._passing_release_notes().replace(
                " It is not a final replacement for old `main`.",
                "",
            )
            self._write_repo(root, self._passing_matrix(), release_notes_text=release_notes)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-final-replacement-denial-missing",
                        "section 1 must state that M1 is not a final replacement for "
                        "old main",
                    )
                ],
            )

    def test_release_notes_subset_claim_must_state_subset_scope(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            subset_row = (
                "| P-QEMU-01-SW | Subset of `configuration/tests/qemu/01.cfg` | "
                "Software-only subset | `configs/experiments/parity/qemu/01.yaml`; "
                "suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. This does not certify "
                "the full P-QEMU-01 application row. |\n"
            )
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog",
                subset_row + "\n## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "| `P-QEMU-01` | QEMU infrastructure |\n",
                "| `P-QEMU-01` | QEMU infrastructure |\n"
                "| `P-QEMU-01-SW` | Full P-QEMU-01 application path |\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\n"
                "Matrix row ID: `P-QEMU-01`\n"
                "Matrix row ID: `P-QEMU-01-SW`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-subset-scope-missing",
                        "P-QEMU-01-SW section 3 claim must state its scoped subset "
                        "boundary; missing software-only, subset",
                    )
                ],
            )

    def test_release_notes_local_subset_claim_must_state_local_resource_scope(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            subset_row = (
                "| P-QEMU-01-SW-LOCAL | Subset of `configuration/tests/qemu/01.cfg` | "
                "Software-only local subset | "
                "`configs/experiments/parity/qemu/01.yaml`; "
                "suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. This does not certify "
                "the exact legacy resource shape or full P-QEMU-01 application row. |\n"
            )
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog",
                subset_row + "\n## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "| `P-QEMU-01` | QEMU infrastructure |\n",
                "| `P-QEMU-01` | QEMU infrastructure |\n"
                "| `P-QEMU-01-SW-LOCAL` | Software-only subset of P-QEMU-01 |\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\n"
                "Matrix row ID: `P-QEMU-01`\n"
                "Matrix row ID: `P-QEMU-01-SW-LOCAL`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-subset-scope-missing",
                        "P-QEMU-01-SW-LOCAL section 3 claim must state its scoped "
                        "subset boundary; missing single-host, cpu-capped",
                    )
                ],
            )

    def test_release_notes_must_list_nonready_module_backlog_items(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog\n",
                "## 5. Module Certification Backlog\n\n"
                "| Module Family | Current Evidence Shape | Status | "
                "Required Before Public Claim |\n"
                "| --- | --- | --- | --- |\n"
                "| `text_translation` | Application module exists. | `ported-unverified` | "
                "Add example config, success detector, and VM-backed evidence. |\n",
            )
            self._write_repo(root, matrix_text)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-nonready-module-missing",
                        "text_translation module status is 'ported-unverified' in the "
                        "matrix but absent from section 4",
                    )
                ],
            )

    def test_release_notes_nonready_module_check_accepts_hyphenated_mentions(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog\n",
                "## 5. Module Certification Backlog\n\n"
                "| Module Family | Current Evidence Shape | Status | "
                "Required Before Public Claim |\n"
                "| --- | --- | --- | --- |\n"
                "| `baremetal` provider | Provider code exists. | `ported-unverified` | "
                "Decide support target and add host/cluster certification path. |\n",
            )
            release_notes = self._passing_release_notes().replace(
                "Nothing else in this tiny fixture.",
                "Broader bare-metal provider support remains unclaimed.",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)

            self.assertEqual(check_release_matrix.find_matrix_issues(root), [])

    def test_release_notes_known_limitations_must_include_host_helper_blocker(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = (
                self._passing_matrix()
                + "\n## 8. Next Steps\n\n"
                "Refresh `HOSTCTL_INTERFACE_VERSION` and `prime-registry-cache`.\n"
            )
            self._write_repo(root, matrix_text)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-known-limitation-missing",
                        "host-helper-interface: section 5 must mention the "
                        "host-helper interface and cache-prime blocker",
                    )
                ],
            )

    def test_release_notes_must_keep_pretag_gate_command_order(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            release_notes = self._passing_release_notes().replace(
                "sudo -n /usr/local/bin/continuum-hostctl verify\n"
                "sh scripts/test/setup_agent_host.sh verify\n",
                "sh scripts/test/setup_agent_host.sh verify\n"
                "sudo -n /usr/local/bin/continuum-hostctl verify\n",
            )
            self._write_repo(root, self._passing_matrix(), release_notes_text=release_notes)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-pretag-command-order",
                        "section 7 lists 'sh scripts/test/setup_agent_host.sh verify' "
                        "before 'sudo -n /usr/local/bin/continuum-hostctl verify'; "
                        "keep pre-tag commands in documented order",
                    )
                ],
            )

    def test_release_notes_must_not_duplicate_pretag_gate_commands(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            duplicate = "python3 scripts/test/check_release_matrix.py"
            release_notes = self._passing_release_notes().replace(
                "%s\n" % (duplicate,),
                "%s\n%s\n" % (duplicate, duplicate),
            )
            self._write_repo(root, self._passing_matrix(), release_notes_text=release_notes)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-pretag-command-duplicate",
                        "section 7 lists '%s' 2 times; keep one canonical "
                        "pre-tag command" % (duplicate,),
                    )
                ],
            )

    def test_preferred_host_sequence_must_keep_contiguous_numbering(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "## 4. Old-Main Provider And Topology Parity",
                "Preferred M1 host command sequence:\n\n"
                "1. `scripts/test/run_cloud_static_audit.sh`\n"
                "2. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`\n"
                "2. `sudo -n /usr/local/bin/continuum-hostctl verify`\n"
                "4. `sh scripts/test/setup_agent_host.sh verify`\n"
                "5. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_infra_parity`\n\n"
                "## 4. Old-Main Provider And Topology Parity",
            )
            self._write_repo(root, matrix_text)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "matrix-host-command-numbering",
                        "Preferred M1 host command sequence lists "
                        "'sudo -n /usr/local/bin/continuum-hostctl verify' "
                        "as item 2; expected item 3",
                    )
                ],
            )

    def test_preferred_host_sequence_must_include_ready_suite_wrapper_commands(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "## 4. Old-Main Provider And Topology Parity",
                "Preferred M1 host command sequence:\n\n"
                "1. `scripts/test/run_cloud_static_audit.sh`\n"
                "2. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`\n"
                "3. `sudo -n /usr/local/bin/continuum-hostctl verify`\n"
                "4. `sh scripts/test/setup_agent_host.sh verify`\n\n"
                "## 4. Old-Main Provider And Topology Parity",
            )
            self._write_repo(root, matrix_text)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "matrix-host-ready-suite-command-missing",
                        "P-QEMU-01 uses ready suite qemu_infra_parity but Preferred "
                        "M1 host command sequence is missing 'sudo -n -u "
                        "continuum-smoke /usr/local/bin/run-continuum-smoke "
                        "qemu_infra_parity'",
                    )
                ],
            )

    def test_preferred_host_sequence_must_include_helper_setup_commands(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "## 4. Old-Main Provider And Topology Parity",
                "Preferred M1 host command sequence:\n\n"
                "1. `scripts/test/run_cloud_static_audit.sh`\n"
                "2. `sudo -n /usr/local/bin/continuum-hostctl verify`\n"
                "3. `sh scripts/test/setup_agent_host.sh verify`\n"
                "4. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_infra_parity`\n\n"
                "## 4. Old-Main Provider And Topology Parity",
            )
            self._write_repo(root, matrix_text)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "matrix-host-required-command-missing",
                        "Preferred M1 host command sequence is missing "
                        "'sudo -n /usr/local/bin/continuum-hostctl sync-repo'",
                    )
                ],
            )

    def test_subset_row_parent_must_exist(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            subset_row = (
                "| P-QEMU-02-SW | Subset of `configuration/tests/qemu/01.cfg` | "
                "Software-only subset | `configs/experiments/parity/qemu/01.yaml`; "
                "suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. This does not certify "
                "the full P-QEMU-02 application row. |\n"
            )
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog",
                subset_row + "\n## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "| `P-QEMU-01` | QEMU infrastructure |\n",
                "| `P-QEMU-01` | QEMU infrastructure |\n"
                "| `P-QEMU-02-SW` | Software-only subset fixture |\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\n"
                "Matrix row ID: `P-QEMU-01`\n"
                "Matrix row ID: `P-QEMU-02-SW`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "subset-row-parent-missing",
                        "P-QEMU-02-SW is a subset row but parent row P-QEMU-02 "
                        "is absent from the matrix",
                    )
                ],
            )

    def test_subset_row_must_not_masquerade_as_full_row(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            subset_row = (
                "| P-QEMU-01-SW | `configuration/tests/qemu/01.cfg` | "
                "Software-only path | `configs/experiments/parity/qemu/01.yaml`; "
                "suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
            )
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog",
                subset_row + "\n## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "| `P-QEMU-01` | QEMU infrastructure |\n",
                "| `P-QEMU-01` | QEMU infrastructure |\n"
                "| `P-QEMU-01-SW` | Software-only subset fixture of P-QEMU-01 |\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\n"
                "Matrix row ID: `P-QEMU-01`\n"
                "Matrix row ID: `P-QEMU-01-SW`\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "subset-row-legacy-scope-missing",
                        "P-QEMU-01-SW must describe its legacy scope as a subset of "
                        "P-QEMU-01",
                    ),
                    check_release_matrix.MatrixIssue(
                        "subset-row-noncertification-missing",
                        "P-QEMU-01-SW must state that it does not certify parent row "
                        "P-QEMU-01",
                    ),
                ],
            )

    def test_ready_row_suite_requires_matching_pretag_wrapper_command(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            extra_config = (
                "configs/experiments/parity/qemu_kubeedge_image/"
                "06_kubeedge_image_classification.yaml"
            )
            extra_row = (
                "| M1-QEMU-IMAGE | application parity | `%s`; "
                "suite `qemu_kubeedge_image_parity` | VM evidence | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
            ) % (extra_config,)
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog",
                extra_row + "\n## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "| `P-QEMU-01` | QEMU infrastructure |\n",
                "| `P-QEMU-01` | QEMU infrastructure |\n"
                "| `M1-QEMU-IMAGE` | Image parity fixture |\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            config_path = root / extra_config
            config_path.parent.mkdir(parents=True)
            config_path.write_text("kind: ContinuumExperiment\n", encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\n"
                "Matrix row ID: `P-QEMU-01`\n"
                "Matrix row ID: `M1-QEMU-IMAGE`\n",
                encoding="utf-8",
            )
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps(
                    {
                        "test_suites": {
                            "qemu_infra_parity": {
                                "directories": ["configs/experiments/parity/qemu/"]
                            },
                            "qemu_kubeedge_image_parity": {
                                "directories": [
                                    "configs/experiments/parity/qemu_kubeedge_image/"
                                ]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-ready-suite-command-missing",
                        "M1-QEMU-IMAGE uses ready suite qemu_kubeedge_image_parity "
                        "but section 7 is missing 'sudo -n -u continuum-smoke "
                        "/usr/local/bin/run-continuum-smoke qemu_kubeedge_image_parity'",
                    )
                ],
            )

    def test_ready_row_suite_requires_known_pretag_wrapper_mapping(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            extra_config = "configs/experiments/custom/01_custom.yaml"
            extra_row = (
                "| M1-CUSTOM | custom module | `%s`; suite `custom_cert_suite` | "
                "VM evidence | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
            ) % (extra_config,)
            matrix_text = self._passing_matrix().replace(
                "## 5. Module Certification Backlog",
                extra_row + "\n## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "| `P-QEMU-01` | QEMU infrastructure |\n",
                "| `P-QEMU-01` | QEMU infrastructure |\n"
                "| `M1-CUSTOM` | Custom certified fixture |\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            config_path = root / extra_config
            config_path.parent.mkdir(parents=True)
            config_path.write_text("kind: ContinuumExperiment\n", encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                "# evidence\n\n"
                "Matrix row ID: `P-QEMU-01`\n"
                "Matrix row ID: `M1-CUSTOM`\n",
                encoding="utf-8",
            )
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps(
                    {
                        "test_suites": {
                            "qemu_infra_parity": {
                                "directories": ["configs/experiments/parity/qemu/"]
                            },
                            "custom_cert_suite": {
                                "directories": ["configs/experiments/custom/"]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-ready-suite-wrapper-unknown",
                        "M1-CUSTOM uses ready suite custom_cert_suite but no pre-tag "
                        "wrapper command mapping exists",
                    )
                ],
            )

    def test_release_notes_must_not_list_nonready_suite_wrapper_commands(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "\n## 5. Module Certification Backlog",
                "\n| P-QEMU-02 | legacy | surface | no yaml; "
                "suite `qemu_kubeedge_image_parity` | `ported-unverified` | "
                "Run fresh VM evidence before claiming support. |\n\n"
                "## 5. Module Certification Backlog",
            )
            release_notes = self._passing_release_notes().replace(
                "Nothing else in this tiny fixture.",
                "`P-QEMU-02` remains unclaimed.",
            ).replace(
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_openfaas_software_parity\n",
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_openfaas_software_parity\n"
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_kubeedge_image_parity\n",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes)
            (root / "configs" / "experiments" / "parity" / "qemu_kubeedge_image").mkdir(
                parents=True
            )
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps(
                    {
                        "test_suites": {
                            "qemu_infra_parity": {
                                "directories": ["configs/experiments/parity/qemu/"]
                            },
                            "qemu_kubeedge_image_parity": {
                                "directories": [
                                    "configs/experiments/parity/qemu_kubeedge_image/"
                                ]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(
                    row_id="P-QEMU-02",
                    action_snapshot="Run fresh VM evidence before claiming support.",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "release-notes-nonready-suite-command-listed",
                        "P-QEMU-02 uses non-ready suite qemu_kubeedge_image_parity "
                        "but section 7 lists 'sudo -n -u continuum-smoke "
                        "/usr/local/bin/run-continuum-smoke qemu_kubeedge_image_parity'",
                    )
                ],
            )

    def test_unknown_claim_status_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix().replace("`certified`", "`maybe-ready`"),
                release_notes_text=self._passing_release_notes().replace(
                    "2. `docs/release_evidence_example.md`\n",
                    "",
                ),
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "claim-row-invalid-status",
                        "P-QEMU-01 uses unknown status 'maybe-ready'",
                    )
                ],
            )

    def test_unknown_module_status_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_repo(
                root,
                self._passing_matrix()
                + "| `qemu` provider | evidence | `half-certified` | run tests |\n",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "module-row-invalid-status",
                        "`qemu` provider uses unknown status 'half-certified'",
                    )
                ],
            )

    def test_module_backlog_certified_rows_must_be_ready(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "\n## 5. Module Certification Backlog",
                "\n| P-QEMU-02 | legacy | surface | no yaml | `ported-unverified` | "
                "Run fresh VM evidence before claiming support. |\n\n"
                "## 5. Module Certification Backlog\n"
                "| `qemu` provider | evidence | `certified` for `P-QEMU-02` only | "
                "run tests |\n",
            )
            release_notes_text = self._passing_release_notes().replace(
                "Nothing else in this tiny fixture.",
                "`P-QEMU-02` remains unclaimed.",
            )
            self._write_repo(root, matrix_text, release_notes_text=release_notes_text)
            (root / "docs" / "old_main_parity_issue_seed.md").write_text(
                self._parity_backlog(
                    row_id="P-QEMU-02",
                    action_snapshot="Run fresh VM evidence before claiming support.",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "module-row-certified-unready-row",
                        "`qemu` provider claims certified row P-QEMU-02 but matrix "
                        "status is 'ported-unverified'",
                    )
                ],
            )

    def test_module_backlog_certified_rows_must_exist(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            matrix_text = self._passing_matrix().replace(
                "\n## 5. Module Certification Backlog",
                "\n## 5. Module Certification Backlog\n"
                "| `qemu` provider | evidence | `certified` for `P-QEMU-99` only | "
                "run tests |\n",
            )
            self._write_repo(root, matrix_text)

            self.assertEqual(
                check_release_matrix.find_matrix_issues(root),
                [
                    check_release_matrix.MatrixIssue(
                        "module-row-certified-unknown-row",
                        "`qemu` provider claims certified row P-QEMU-99 but that row "
                        "is absent from the matrix",
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
