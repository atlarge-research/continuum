"""Unit tests for the public release-claims checker."""

# pylint: disable=missing-class-docstring,missing-function-docstring,too-many-public-methods

import tempfile
import unittest
from pathlib import Path

from scripts.test import check_release_claims


class CheckReleaseClaimsTests(unittest.TestCase):
    def _write_public_docs(self, root: Path, overrides=None):
        overrides = overrides or {}
        matrix_reference = "docs/release_certification_matrix.md"
        docs = {
            "README.md": "Release support is tracked in %s.\n" % (matrix_reference,),
            "docs/configuration_reference.md": (
                "This schema is not a support matrix; see %s.\n" % (matrix_reference,)
            ),
            "docs/migration_notes.md": (
                "Migration guidance is not a support matrix; see %s.\n"
                % (matrix_reference,)
            ),
            "docs/cheatsheet.md": "For support status, see %s.\n" % (matrix_reference,),
            "docs/operational_testing_strategy.md": (
                "Runtime support claims are bounded by %s.\n" % (matrix_reference,)
            ),
            "docs/smoke_runner_isolation.md": (
                "Host-runner commands are not support claims; see %s.\n"
                % (matrix_reference,)
            ),
            "docs/phase_d_handoff.md": (
                "Historical handoff evidence is bounded by %s.\n" % (matrix_reference,)
            ),
            "docs/rework_plan_stack.md": (
                "Planning authority keeps claims aligned with %s.\n" % (matrix_reference,)
            ),
            "docs/rework_kickoff.md": (
                "First-read release status is tracked in %s.\n" % (matrix_reference,)
            ),
            "docs/rework_milestone_release_plan.md": (
                "Intermediate releases use %s for exact claims.\n" % (matrix_reference,)
            ),
            "docs/old_main_parity_issue_seed.md": (
                "Issue seeds keep claims bounded by %s.\n" % (matrix_reference,)
            ),
            "docs/post_release_roadmap.md": (
                "Future work must keep claims aligned with %s.\n" % (matrix_reference,)
            ),
            "docs/release_notes_m1_draft.md": (
                "# Release Notes\n\n"
                "Support is limited to %s.\n\n"
                "Avoid wording like:\n\n"
                "1. \"QEMU core\"\n"
                "2. \"Continuum supports GCP/AWS on this release\"\n"
            )
            % (matrix_reference,),
            "configuration/README.md": (
                "Legacy configs are historical; release support is tracked in %s.\n"
                % (matrix_reference,)
            ),
        }
        docs.update(overrides)
        for path, text in docs.items():
            full_path = root / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(text, encoding="utf-8")

    def test_current_release_docs_have_no_claim_drift(self):
        self.assertEqual(check_release_claims.find_release_claim_issues(), [])

    def test_minimal_public_docs_pass(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root)

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_missing_matrix_reference_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root, {"docs/cheatsheet.md": "Quick commands only.\n"})

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "release-doc-matrix-reference-missing",
                        "docs/cheatsheet.md must point support claims to "
                        "docs/release_certification_matrix.md",
                    )
                ],
            )

    def test_qemu_core_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "The QEMU core is ready.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "qemu-core-claim",
                        "README.md:2: describe QEMU as a provider module, not Continuum core",
                    )
                ],
            )

    def test_qemu_part_of_core_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "QEMU is part of the Continuum core.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "qemu-core-claim",
                        "README.md:2: describe QEMU as a provider module, not Continuum core",
                    )
                ],
            )

    def test_qemu_not_part_of_core_text_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "QEMU is not part of the Continuum core.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_release_matrix_doc_claim_drift_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "The QEMU core is ready.\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "qemu-core-claim",
                        "docs/release_certification_matrix.md:1: describe QEMU as a "
                        "provider module, not Continuum core",
                    )
                ],
            )

    def test_operator_doc_claim_drift_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/smoke_runner_isolation.md": (
                        "Host-runner commands are not support claims; see "
                        "docs/release_certification_matrix.md.\n"
                        "The QEMU core is ready.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "qemu-core-claim",
                        "docs/smoke_runner_isolation.md:2: describe QEMU as a "
                        "provider module, not Continuum core",
                    )
                ],
            )

    def test_release_evidence_docs_are_scanned_for_claim_drift(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root)
            (root / "docs" / "release_evidence_example.md").write_text(
                "Evidence is bounded by docs/release_certification_matrix.md.\n"
                "The QEMU core is ready.\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "qemu-core-claim",
                        "docs/release_evidence_example.md:2: describe QEMU as a "
                        "provider module, not Continuum core",
                    )
                ],
            )

    def test_release_evidence_docs_must_reference_matrix(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root)
            (root / "docs" / "release_evidence_example.md").write_text(
                "Evidence for local QEMU smoke.\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "release-doc-matrix-reference-missing",
                        "docs/release_evidence_example.md must point support claims to "
                        "docs/release_certification_matrix.md",
                    )
                ],
            )

    def test_unlisted_docs_are_scanned_without_matrix_reference_requirement(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root)
            (root / "docs" / "runtime_execution_pipeline.md").write_text(
                "The QEMU core is ready.\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "qemu-core-claim",
                        "docs/runtime_execution_pipeline.md:1: describe QEMU as a "
                        "provider module, not Continuum core",
                    )
                ],
            )

    def test_nested_configuration_docs_are_scanned_for_support_claims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root)
            (root / "configuration" / "network_validation").mkdir(parents=True)
            (root / "configuration" / "network_validation" / "README.md").write_text(
                "Continuum supports AWS in this release.\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "configuration/network_validation/README.md:1: do not claim "
                        "GCP/AWS support without certified cloud evidence",
                    )
                ],
            )

    def test_release_note_avoid_wording_examples_are_ignored(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/release_notes_m1_draft.md": (
                        "Support is limited to docs/release_certification_matrix.md.\n\n"
                        "Avoid wording like:\n\n"
                        "1. \"QEMU core\"\n"
                        "2. \"Continuum supports GCP/AWS on this release\"\n"
                        "3. \"All shipped YAML examples are release-supported\"\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_cloud_provider_release_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Continuum supports GCP/AWS on this release.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "README.md:2: do not claim GCP/AWS support without certified "
                        "cloud evidence",
                    )
                ],
            )

    def test_caveated_cloud_provider_release_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Continuum supports AWS in this release; requires credentials.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "README.md:2: do not claim GCP/AWS support without certified "
                        "cloud evidence",
                    )
                ],
            )

    def test_cloud_provider_evidence_prerequisite_text_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "AWS rows require cloud-backed evidence before they can be "
                        "release-supported.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_full_main_replacement_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "The rework is a full replacement for main.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "full-main-replacement-claim",
                        "README.md:2: describe M1 as an intermediate milestone, not a "
                        "final main replacement",
                    )
                ],
            )

    def test_final_m1_release_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Continuum M1 is the final release for the rework.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "final-or-full-m1-release-claim",
                        "README.md:2: describe M1 as an intermediate milestone or "
                        "pre-release, not a final/full release",
                    )
                ],
            )

    def test_intermediate_m1_release_wording_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Continuum M1 is an intermediate milestone release.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_negated_final_release_text_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "M1 is not a final release for the rework.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_application_parity_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "KubeEdge application parity is certified for this milestone.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "application-parity-release-claim",
                        "README.md:2: certify only exact software-only subsets until full "
                        "application rows have evidence",
                    )
                ],
            )

    def test_caveated_application_parity_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Mist application parity is certified but requires a registry cache.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "application-parity-release-claim",
                        "README.md:2: certify only exact software-only subsets until full "
                        "application rows have evidence",
                    )
                ],
            )

    def test_exact_certified_kubeedge_application_row_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "KubeEdge application parity is certified only for P-QEMU-06.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_exact_certified_kubeedge_application_row_in_inline_code_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "KubeEdge application parity is certified only for `P-QEMU-06`.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_exact_certified_mist_application_row_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Mist application parity is certified only for `P-QEMU-07`.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_full_qemu_parity_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Full QEMU parity is certified for this milestone.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "full-qemu-parity-release-claim",
                        "README.md:2: claim only exact QEMU parity rows until all old-main "
                        "QEMU rows have evidence",
                    )
                ],
            )

    def test_inline_code_identifiers_do_not_create_parity_claim(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/release_certification_matrix.md": (
                        "| P-QEMU-04 | `configuration/tests/qemu/04_infraonly-all.cfg` | "
                        "QEMU infrastructure | `configs/parity/qemu/04.yaml`; "
                        "suite `qemu_infra_parity` | `certified` | Evidence doc. |\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_selected_qemu_parity_wording_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "This milestone certifies selected old-main QEMU parity rows.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_yaml_examples_release_claim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/configuration_reference.md": (
                        "Support is tracked in docs/release_certification_matrix.md.\n"
                        "All shipped YAML examples are release-supported.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "all-yaml-examples-release-supported",
                        "docs/configuration_reference.md:2: shipped examples are parser coverage "
                        "unless matrix rows certify them",
                    )
                ],
            )

    def test_migration_notes_are_scanned_for_support_claims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/migration_notes.md": (
                        "Migration guidance is bounded by "
                        "docs/release_certification_matrix.md.\n"
                        "All shipped YAML examples are release-supported.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "all-yaml-examples-release-supported",
                        "docs/migration_notes.md:2: shipped examples are parser coverage "
                        "unless matrix rows certify them",
                    )
                ],
            )

    def test_legacy_configuration_readme_is_scanned_for_support_claims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "configuration/README.md": (
                        "Legacy config status is bounded by "
                        "docs/release_certification_matrix.md.\n"
                        "Continuum supports AWS in this release.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "configuration/README.md:2: do not claim GCP/AWS support "
                        "without certified cloud evidence",
                    )
                ],
            )

    def test_planning_stack_docs_are_scanned_for_support_claims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/rework_plan_stack.md": (
                        "Planning authority keeps claims aligned with "
                        "docs/release_certification_matrix.md.\n"
                        "Full QEMU parity is certified by this planning stack.\n"
                    ),
                    "docs/rework_kickoff.md": (
                        "First-read release status is tracked in "
                        "docs/release_certification_matrix.md.\n"
                        "The kickoff says Continuum supports AWS in this release.\n"
                    ),
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "full-qemu-parity-release-claim",
                        "docs/rework_plan_stack.md:2: claim only exact QEMU parity rows "
                        "until all old-main QEMU rows have evidence",
                    ),
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "docs/rework_kickoff.md:2: do not claim GCP/AWS support "
                        "without certified cloud evidence",
                    ),
                ],
            )

    def test_operational_testing_strategy_is_scanned_for_support_claims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/operational_testing_strategy.md": (
                        "Runtime support claims are bounded by "
                        "docs/release_certification_matrix.md.\n"
                        "GCP is release-supported by the operational test plan.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "docs/operational_testing_strategy.md:2: do not claim GCP/AWS "
                        "support without certified cloud evidence",
                    )
                ],
            )

    def test_post_release_roadmap_is_scanned_for_support_claims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/post_release_roadmap.md": (
                        "Future work must keep claims aligned with "
                        "docs/release_certification_matrix.md.\n"
                        "Continuum supports AWS in this release train.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "docs/post_release_roadmap.md:2: do not claim GCP/AWS support "
                        "without certified cloud evidence",
                    )
                ],
            )

    def test_old_main_parity_issue_seed_is_scanned_for_support_claims(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/old_main_parity_issue_seed.md": (
                        "Issue seeds keep claims bounded by "
                        "docs/release_certification_matrix.md.\n"
                        "Port GCP cloud-only infrastructure and certify it.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "cloud-provider-release-claim",
                        "docs/old_main_parity_issue_seed.md:2: do not claim GCP/AWS "
                        "support without certified cloud evidence",
                    )
                ],
            )

    def test_negated_historical_cloud_text_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Historically, Continuum has supported Google Cloud, but it is not "
                        "release-certified here.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_module_readiness_overclaim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "docs/release_certification_matrix.md": (
                        "`openfaas` has VM-backed evidence with gateway readiness checks.\n"
                    )
                },
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "module-readiness-overclaim",
                        "docs/release_certification_matrix.md:1: claim only retained "
                        "software-phase evidence unless readiness markers are explicit",
                    )
                ],
            )

    def test_retained_readiness_snapshot_overclaim_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(root)
            (root / "docs" / "release_evidence_example.md").write_text(
                "Evidence is bounded by docs/release_certification_matrix.md.\n"
                "The retained readiness snapshot showed a healthy gateway.\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_claims.find_release_claim_issues(root),
                [
                    check_release_claims.ReleaseClaimIssue(
                        "module-readiness-overclaim",
                        "docs/release_evidence_example.md:2: claim only retained "
                        "software-phase evidence unless readiness markers are explicit",
                    )
                ],
            )

    def test_negated_module_readiness_overclaim_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "This evidence does not certify gateway-specific OpenFaaS readiness "
                        "beyond software-phase completion.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])

    def test_negated_full_qemu_parity_text_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_public_docs(
                root,
                {
                    "README.md": (
                        "Release support is tracked in docs/release_certification_matrix.md.\n"
                        "Do not claim full QEMU parity until all old-main rows have evidence.\n"
                    )
                },
            )

            self.assertEqual(check_release_claims.find_release_claim_issues(root), [])


if __name__ == "__main__":
    unittest.main()
