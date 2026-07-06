"""Unit tests for local release evidence artifact checks."""

# pylint: disable=duplicate-code,missing-class-docstring,missing-function-docstring
# pylint: disable=too-many-arguments,too-many-lines,too-many-public-methods

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.test import check_release_evidence_artifacts

TEST_RESULT_PATH_RE = re.compile(r"(/[^`\s]+/\.continuum/test_results/test_results_[^`\s]+\.json)")


class CheckReleaseEvidenceArtifactsTests(unittest.TestCase):
    def _write_matrix(
        self,
        root: Path,
        config_path=None,
        evidence_doc="docs/release_evidence_example.md",
        claim_text=None,
    ):
        if config_path and claim_text:
            row = (
                "| P-QEMU-01 | `%s` | %s | `certified` | "
                "Evidence: `%s`. |\n"
            ) % (config_path, claim_text, evidence_doc)
        elif config_path:
            row = (
                "| P-QEMU-01 | `%s` | `certified` | "
                "Evidence: `%s`. |\n"
            ) % (config_path, evidence_doc)
        else:
            row = (
                "| P-QEMU-01 | `certified` | "
                "Evidence: `%s`. |\n"
            ) % (evidence_doc,)
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "release_certification_matrix.md").write_text(
            "| ID | Config | Status | Certification Action |\n"
            "| --- | --- | --- | --- |\n"
            + row,
            encoding="utf-8",
        )

    def _write_test_results(
        self,
        path: Path,
        failed: int = 0,
        success_reason=None,
        config_path="configs/experiments/parity/qemu/01.yaml",
    ):
        if success_reason is None:
            success_reason = (
                "Success: exit_code=0, experiment_lock_written, state_file_written, "
                "state_phase=infrastructure, resume_contract_match"
            )
        path.parent.mkdir(parents=True)
        timestamp = path.stem[len("test_results_") :]
        artifacts_dir = path.parent / path.stem
        artifact_dir = artifacts_dir / "01_fixture"
        artifact_dir.mkdir(parents=True)
        continuum_root = path.parent.parent
        state_phase = self._state_phase_from_success_reason(success_reason)
        contract = {"hash": "sha256:fixture-contract"}
        (continuum_root / "experiment_lock.yaml").write_text(
            (
                "schema_version: 1\n"
                "kind: ContinuumExperimentLock\n"
                "sources:\n"
                "  experiment: /repo/%s\n"
                "resume_contract:\n"
                "  hash: sha256:fixture-contract\n"
            )
            % (config_path,),
            encoding="utf-8",
        )
        (continuum_root / "state.json").write_text(
            json.dumps(
                {
                    "phase_completed": state_phase,
                    "resume_contract": contract,
                }
            ),
            encoding="utf-8",
        )
        stdout_artifact = artifact_dir / "stdout.txt"
        stderr_artifact = artifact_dir / "stderr.txt"
        metadata_artifact = artifact_dir / "metadata.json"
        stdout_artifact.write_text("fixture stdout\n", encoding="utf-8")
        stderr_artifact.write_text("", encoding="utf-8")
        result_entry = {
            "config_path": config_path,
            "success": failed == 0,
            "exit_code": 0 if failed == 0 else 1,
            "success_reason": success_reason,
            "start_time": "2026-05-23 18:35:48",
            "execution_time": 1.25,
            "timed_out": False,
            "base_images_rebuilt": [],
            "parameter_overrides": {},
            "stdout_artifact": str(stdout_artifact),
            "stderr_artifact": str(stderr_artifact),
            "metadata_artifact": str(metadata_artifact),
        }
        metadata_artifact.write_text(json.dumps(result_entry), encoding="utf-8")
        path.write_text(
            json.dumps(
                {
                    "timestamp": timestamp,
                    "artifacts_dir": str(artifacts_dir),
                    "total_tests": 1,
                    "passed": 1 if failed == 0 else 0,
                    "failed": failed,
                    "results": [result_entry],
                }
            ),
            encoding="utf-8",
        )

    def _state_phase_from_success_reason(self, success_reason: str) -> str:
        for token in success_reason.split(","):
            token = token.strip()
            if token.startswith("state_phase="):
                return token.split("=", 1)[1]
        return "infrastructure"

    def _append_test_result_entry(
        self,
        summary_path: Path,
        artifact_name: str,
        config_path: str,
        success_reason: str,
    ):
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        artifacts_dir = Path(payload["artifacts_dir"])
        artifact_dir = artifacts_dir / artifact_name
        artifact_dir.mkdir(parents=True)
        stdout_artifact = artifact_dir / "stdout.txt"
        stderr_artifact = artifact_dir / "stderr.txt"
        metadata_artifact = artifact_dir / "metadata.json"
        stdout_artifact.write_text("fixture stdout\n", encoding="utf-8")
        stderr_artifact.write_text("", encoding="utf-8")
        result_entry = {
            "config_path": config_path,
            "success": True,
            "exit_code": 0,
            "success_reason": success_reason,
            "start_time": "2026-05-23 18:35:48",
            "execution_time": 1.25,
            "timed_out": False,
            "base_images_rebuilt": [],
            "parameter_overrides": {},
            "stdout_artifact": str(stdout_artifact),
            "stderr_artifact": str(stderr_artifact),
            "metadata_artifact": str(metadata_artifact),
        }
        metadata_artifact.write_text(json.dumps(result_entry), encoding="utf-8")
        payload["results"].append(result_entry)
        payload["total_tests"] = len(payload["results"])
        payload["passed"] = len(payload["results"])
        summary_path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_config_targets(
        self,
        root: Path,
        config_path="configs/experiments/parity/qemu/01.yaml",
        targets="[infrastructure]",
        environment=None,
        software=None,
        benchmark_pipeline=False,
        network_emulation=False,
    ):
        config_file = root / config_path
        config_file.parent.mkdir(parents=True, exist_ok=True)
        use_text = ""
        if environment is not None or software is not None:
            use_lines = ["use:\n"]
            if environment is not None:
                use_lines.append("  environment: %s\n" % (environment,))
            if software is not None:
                use_lines.append("  software: %s\n" % (software,))
            use_text = "".join(use_lines)
        benchmark_text = ""
        if benchmark_pipeline:
            benchmark_text = (
                "benchmark:\n"
                "  pipeline:\n"
                "    - id: fixture-benchmark\n"
                "      type: image_classification\n"
            )
        network_text = ""
        if network_emulation:
            network_text = (
                "infrastructure:\n"
                "  network:\n"
                "    emulation: true\n"
            )
        config_file.write_text(
            (
                "---\n"
                "schema_version: 1\n"
                "kind: ContinuumExperiment\n"
                + use_text
                + "run:\n"
                "  targets: %s\n" % (targets,)
                + benchmark_text
                + network_text
            ),
            encoding="utf-8",
        )

    def _required_gates_text(self, failing_gate=None):
        lines = ["## Required Gates\n"]
        for gate in check_release_evidence_artifacts.REQUIRED_CLOUD_AUDIT_GATES:
            status = "FAIL (1)" if gate == failing_gate else "PASS"
            lines.append("- %s: %s\n" % (gate, status))
        lines.append("\n")
        return "".join(lines)

    def _release_readiness_text(
        self,
        docs_total=0,
        claim_total=0,
        matrix_total=0,
        artifact_total=0,
        pretag_total=9,
        infra_prereq_status="OK",
        artifact_status="OK",
        pretag_status="FINDINGS OR UNAVAILABLE (1)",
        include_docs_total=True,
        include_claim_total=True,
        include_matrix_total=True,
        include_artifact_status=True,
        include_pretag_status=True,
        include_artifact_total=True,
        include_pretag_total=True,
    ):
        lines = ["## Informational Checks\n"]
        if include_artifact_status:
            lines.append("- release evidence artifact audit: %s\n" % (artifact_status,))
        if include_pretag_status:
            lines.append("- M1 pre-tag readiness check: %s\n" % (pretag_status,))
        if infra_prereq_status is not None:
            lines.append(
                "- QEMU infra parity suite prerequisites: %s\n" % (infra_prereq_status,)
            )
        lines.extend(["\n", "## Output Excerpts\n"])
        if include_docs_total:
            lines.append("### docs path reference check\n")
            lines.append("TOTAL_MISSING_REFERENCES=%s\n" % (docs_total,))
        if include_claim_total:
            lines.append("### public release-claims check\n")
            lines.append("TOTAL_RELEASE_CLAIM_ISSUES=%s\n" % (claim_total,))
        if include_matrix_total:
            lines.append("### release certification matrix check\n")
            lines.append("TOTAL_RELEASE_MATRIX_ISSUES=%s\n" % (matrix_total,))
        if include_artifact_total:
            lines.append("### release evidence artifact audit\n")
            lines.append("TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=%s\n" % (artifact_total,))
        if include_pretag_total:
            lines.append("### M1 pre-tag readiness check\n")
            lines.append("TOTAL_RELEASE_PRETAG_ISSUES=%s\n" % (pretag_total,))
        return "".join(lines)

    def _evidence_text(
        self,
        body: str,
        omitted_context_field=None,
        include_limitations=True,
        include_runtime_scope=True,
        include_artifact_root=True,
        matrix_row_id="P-QEMU-01",
        git_commit="`abcdef0`",
        date="2026-05-23",
        runtime_targets="`infrastructure`",
        mentioned_config_path="configs/experiments/parity/qemu/01.yaml",
        provider_prerequisites="Local fixture provider; no cloud credentials",
    ):
        context = {
            "Git commit": git_commit,
            "Tree state": "Dirty fixture tree",
            "Date": date,
            "Runner context": "Fixture runner",
            "Command": "`fixture command`",
            "Provider / host prerequisites": provider_prerequisites,
        }
        if matrix_row_id is not None:
            context["Matrix row ID"] = "`%s`" % (matrix_row_id,)
        if include_runtime_scope:
            context["Runtime targets"] = runtime_targets
        context["Required artifacts checked"] = self._required_artifacts_text(
            body,
            runtime_targets if include_runtime_scope else "",
        )
        lines = ["| Field | Value |\n", "| --- | --- |\n"]
        for field, value in context.items():
            if field == omitted_context_field:
                continue
            lines.append("| %s | %s |\n" % (field, value))
        config_line = (
            "| Config | `%s` |\n" % (mentioned_config_path,)
            if mentioned_config_path
            else ""
        )
        artifact_root_line = ""
        if include_artifact_root and "Artifact root" not in body:
            artifact_root = self._artifact_root_from_body(body)
            if artifact_root:
                artifact_root_line = "| Artifact root | `%s` |\n" % (artifact_root,)
        limitations = (
            "\n## Limitations\n\nThis fixture evidence does not certify broader scope.\n"
            if include_limitations
            else ""
        )
        return "".join(lines) + config_line + artifact_root_line + body + limitations

    def _required_artifacts_text(self, body: str, runtime_targets: str) -> str:
        markers = [
            "test-results summary",
            "experiment lock",
            "state file",
            "stdout/stderr/metadata artifacts",
        ]
        runtime_targets_lower = runtime_targets.lower().replace("`", "")
        for target, marker in (
            ("infrastructure", "infrastructure phase evidence"),
            ("software", "software phase evidence"),
            ("application", "application phase evidence"),
        ):
            if target in runtime_targets_lower:
                markers.append(marker)
        if "cleanup" in runtime_targets_lower or "teardown" in runtime_targets_lower:
            markers.append("teardown evidence")
        body_lower = body.lower()
        if "cloud_static_audit" in body_lower:
            markers.append("cloud-static audit report")
        if ".ndjson" in body_lower:
            markers.append("network NDJSON artifact")
        if "_metrics_manifest.json" in body_lower:
            markers.append("benchmark metrics manifest")
        return ", ".join(markers)

    def _artifact_root_from_body(self, body: str) -> str:
        for match in TEST_RESULT_PATH_RE.findall(body):
            path = Path(match)
            try:
                continuum_index = path.parts.index(".continuum")
            except ValueError:
                continue
            return Path(*path.parts[: continuum_index + 1]).as_posix()
        return ""

    def _write_benchmark_manifest(self, root: Path, columns, row):
        table = root / "artifacts" / "control_plane_metrics.csv"
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text(
            ",".join(columns) + "\n" + ",".join(row) + "\n",
            encoding="utf-8",
        )
        manifest = root / "artifacts" / "control_plane_metrics_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "kind": "ContinuumBenchmarkMetrics",
                    "tables": [{"path": str(table), "rows": 1}],
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_passing_test_results_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [],
            )

    def test_check_artifact_reports_permission_denied(self):
        artifact = check_release_evidence_artifacts.EvidenceArtifact(
            evidence_doc="docs/release_evidence_example.md",
            evidence_path=Path("docs/release_evidence_example.md"),
            path=Path("/retained/metrics_manifest.json"),
            kind="benchmark-metrics-manifest",
            line=12,
        )

        with mock.patch.object(Path, "exists", side_effect=PermissionError("denied")):
            self.assertEqual(
                check_release_evidence_artifacts.check_artifact(artifact),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "artifact-access-failed",
                        "docs/release_evidence_example.md:12 cannot access "
                        "/retained/metrics_manifest.json: denied",
                    )
                ],
            )

    def test_test_results_state_phase_must_match_config_run_targets(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            self._write_config_targets(root, targets="[infrastructure, software]")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    runtime_targets="`infrastructure`, `software`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-state-phase-mismatch",
                        "%s results[0] configs/experiments/parity/qemu/01.yaml "
                        "recorded state_phase=infrastructure expected software "
                        "from run.targets" % (artifact,),
                    )
                ],
            )

    def test_test_results_state_phase_matching_config_run_targets_passes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(root, targets="[infrastructure, software]")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=software, resume_contract_match"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    runtime_targets="`infrastructure`, `software`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_test_results_requires_claimed_lock_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            lock_path = artifact.parent.parent / "experiment_lock.yaml"
            lock_path.unlink()
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-lock-missing",
                        "%s results[0] success_reason claims experiment_lock_written "
                        "but %s is missing" % (artifact, lock_path),
                    )
                ],
            )

    def test_test_results_requires_claimed_state_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            state_path = artifact.parent.parent / "state.json"
            state_path.unlink()
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-state-missing",
                        "%s results[0] success_reason claims state_file_written "
                        "but %s is missing" % (artifact, state_path),
                    )
                ],
            )

    def test_test_results_validates_readable_lock_config_source(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            lock_path = artifact.parent.parent / "experiment_lock.yaml"
            lock_path.write_text(
                (
                    "schema_version: 1\n"
                    "kind: ContinuumExperimentLock\n"
                    "sources:\n"
                    "  experiment: /repo/configs/experiments/other.yaml\n"
                ),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-lock-config-mismatch",
                        "%s results[0] %s sources.experiment=%r expected one of: %s"
                        % (
                            artifact,
                            lock_path,
                            "/repo/configs/experiments/other.yaml",
                            "configs/experiments/parity/qemu/01.yaml",
                        ),
                    )
                ],
            )

    def test_test_results_validates_readable_state_phase(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            state_path = artifact.parent.parent / "state.json"
            state_path.write_text(json.dumps({"phase_completed": "software"}), encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-state-file-phase-mismatch",
                        "%s results[0] %s phase_completed=%r expected infrastructure "
                        "from success_reason" % (artifact, state_path, "software"),
                    )
                ],
            )

    def test_multi_entry_resume_summary_allows_shared_final_state_phase(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            infra_config = "configs/experiments/resume/infra.yaml"
            software_config = "configs/experiments/resume/software.yaml"
            application_config = "configs/experiments/resume/application.yaml"
            self._write_config_targets(root, config_path=infra_config, targets="[infrastructure]")
            self._write_config_targets(root, config_path=software_config, targets="[software]")
            self._write_config_targets(
                root,
                config_path=application_config,
                targets="[application]",
                benchmark_pipeline=True,
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=infra_config)
            self._append_test_result_entry(
                artifact,
                "02_software",
                software_config,
                "Success: exit_code=0, experiment_lock_written, "
                "state_file_written, state_phase=software, resume_contract_match",
            )
            self._append_test_result_entry(
                artifact,
                "03_application",
                application_config,
                "Success: exit_code=0, experiment_lock_written, "
                "state_file_written, state_phase=application, resume_contract_match",
            )
            state_path = artifact.parent.parent / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "phase_completed": "application",
                        "resume_contract": {"hash": "sha256:fixture-contract"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    runtime_targets="`infrastructure`, `software`, `application`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_evidence_doc_runtime_targets_must_cover_config_run_targets(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(root, targets="[infrastructure, software]")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=software, resume_contract_match"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    runtime_targets="`infrastructure`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-runtime-target-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/parity/qemu/01.yaml run.targets "
                        "includes software but Runtime targets='infrastructure' "
                        "does not mention it",
                    )
                ],
            )

    def test_evidence_doc_runtime_targets_must_not_claim_unsupported_phase(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(root, targets="[infrastructure]")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    runtime_targets="infrastructure, application",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-runtime-target-unsupported",
                        "docs/release_evidence_example.md Runtime targets="
                        "'infrastructure, application' claims application but "
                        "no certified config run.targets or retained state_phase "
                        "evidence supports it",
                    )
                ],
            )

    def test_benchmark_application_config_requires_metric_evidence_markers(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                targets="[application]",
                benchmark_pipeline=True,
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=application, "
                    "resume_contract_match"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    runtime_targets="`application`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "benchmark-application-evidence-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/parity/qemu/01.yaml has benchmark "
                        "application pipeline but retained success_reason lacks "
                        "benchmark metric evidence markers",
                    )
                ],
            )

    def test_benchmark_application_config_accepts_metric_manifest_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                targets="[application]",
                benchmark_pipeline=True,
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            table = root / "artifacts" / "metrics.csv"
            table.parent.mkdir(parents=True)
            table.write_text("latency_avg (ms)\n1.0\n", encoding="utf-8")
            manifest = root / "artifacts" / "fixture_metrics_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "kind": "ContinuumBenchmarkMetrics",
                        "tables": [{"path": str(table), "rows": 1}],
                    }
                ),
                encoding="utf-8",
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=application, "
                    "resume_contract_match, benchmark_evidence_found, "
                    "benchmark_metric_tables_found, benchmark_metric_artifacts=%s"
                    % (manifest,)
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Benchmark metric artifact: `%s`\n" % (artifact, manifest),
                    runtime_targets="`application`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_full_control_plane_trace_claim_requires_complete_metric_row(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                targets="[application]",
                benchmark_pipeline=True,
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            manifest = self._write_benchmark_manifest(
                root,
                ["started_application (s)"],
                ["1.0"],
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=application, "
                    "resume_contract_match, benchmark_evidence_found, "
                    "benchmark_metric_tables_found, benchmark_metric_artifacts=%s"
                    % (manifest,)
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Benchmark metric artifact: `%s`\n"
                    "This certifies full control-plane trace reproduction.\n"
                    % (artifact, manifest),
                    runtime_targets="`application`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "control-plane-trace-claim-unverified",
                        "docs/release_evidence_example.md claims full control-plane "
                        "trace reproduction but retained benchmark metrics tables lack "
                        "a complete row for: controller_read_workload (s), "
                        "controller_unpacked_workload (s), scheduler_read_pod (s), "
                        "kubelet_pod_received (s), kubelet_applied_sandbox (s), "
                        "started_application (s)",
                    )
                ],
            )

    def test_full_control_plane_trace_claim_accepts_complete_metric_row(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                targets="[application]",
                benchmark_pipeline=True,
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            columns = check_release_evidence_artifacts.CONTROL_PLANE_TRACE_COLUMNS
            manifest = self._write_benchmark_manifest(
                root,
                columns,
                ["1.0", "2.0", "3.0", "4.0", "5.0", "6.0"],
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=application, "
                    "resume_contract_match, benchmark_evidence_found, "
                    "benchmark_metric_tables_found, benchmark_metric_artifacts=%s"
                    % (manifest,)
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Benchmark metric artifact: `%s`\n"
                    "This certifies full control-plane trace reproduction.\n"
                    % (artifact, manifest),
                    runtime_targets="`application`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_control_plane_trace_limitation_is_not_treated_as_full_claim(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                targets="[application]",
                benchmark_pipeline=True,
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            manifest = self._write_benchmark_manifest(
                root,
                ["started_application (s)"],
                ["1.0"],
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=application, "
                    "resume_contract_match, benchmark_evidence_found, "
                    "benchmark_metric_tables_found, benchmark_metric_artifacts=%s"
                    % (manifest,)
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Benchmark metric artifact: `%s`\n"
                    "This evidence does not certify full control-plane trace reproduction.\n"
                    % (artifact, manifest),
                    runtime_targets="`application`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_claimed_kubernetes_node_ready_stdout_marker_is_required(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=software, resume_contract_match"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "The retained stdout records the Kubernetes node-ready runtime check.\n"
                    % (artifact,),
                    runtime_targets="`software`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-stdout-marker-missing",
                        "docs/release_evidence_example.md claims "
                        "kubernetes-node-ready-runtime-check but retained stdout "
                        "artifacts do not contain: All nodes are Ready",
                    )
                ],
            )

    def test_claimed_kubernetes_node_ready_stdout_marker_passes_when_retained(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=software, resume_contract_match"
                ),
            )
            stdout_artifact = artifact.with_suffix("") / "01_fixture" / "stdout.txt"
            stdout_artifact.write_text(
                "resource_manager.kubernetes: All nodes are Ready\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "The retained stdout records the Kubernetes node-ready runtime check.\n"
                    % (artifact,),
                    runtime_targets="`software`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_local_qemu_config_requires_explicit_host_prerequisites(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(root, config_path=config_path, environment="local-qemu")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Provider profile | `local-qemu` |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    provider_prerequisites="Local fixture provider; no cloud credentials",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-local-qemu-prerequisites-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/parity/qemu/01.yaml uses environment "
                        "local-qemu but Provider / host prerequisites is missing: "
                        "qemu, libvirt, kvm",
                    )
                ],
            )

    def test_local_qemu_host_prerequisites_pass_with_required_markers(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(root, config_path=config_path, environment="local-qemu")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Provider profile | `local-qemu` |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    provider_prerequisites=(
                        "Local QEMU/libvirt/KVM host with SSH access; "
                        "no cloud credentials."
                    ),
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_evidence_doc_must_mention_certified_config_profile_ids(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                environment="local-qemu",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    provider_prerequisites=(
                        "Local QEMU/libvirt/KVM host with SSH access; "
                        "no cloud credentials."
                    ),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-profile-id-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/parity/qemu/01.yaml uses profile "
                        "local-qemu but evidence does not mention it",
                    )
                ],
            )

    def test_evidence_doc_profile_ids_match_exact_tokens(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                environment="local-qemu",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Provider profile | `configs/profiles/environment/local-qemu-cpupin.yaml` |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    provider_prerequisites=(
                        "Local QEMU/libvirt/KVM host with SSH access; "
                        "no cloud credentials."
                    ),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-profile-id-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/parity/qemu/01.yaml uses profile "
                        "local-qemu but evidence does not mention it",
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-profile-field-mismatch",
                        "docs/release_evidence_example.md P-QEMU-01 Provider "
                        "profile='configs/profiles/environment/local-qemu-cpupin.yaml' "
                        "but certified configs use environment profile(s): local-qemu",
                    )
                ],
            )

    def test_single_config_evidence_doc_must_have_profile_fields(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                environment="local-qemu",
                software="fixture-software",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Profile IDs: `local-qemu`, `fixture-software`.\n" % (artifact,),
                    provider_prerequisites=(
                        "Local QEMU/libvirt/KVM host with SSH access; "
                        "no cloud credentials."
                    ),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-profile-field-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/parity/qemu/01.yaml uses environment "
                        "profile local-qemu but has no Provider profile field",
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-profile-field-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/parity/qemu/01.yaml uses software "
                        "profile fixture-software but has no Software profile field",
                    ),
                ],
            )

    def test_evidence_doc_profile_fields_must_match_config_use_profiles(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            self._write_config_targets(
                root,
                config_path=config_path,
                environment="local-qemu",
                software="fixture-software",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Provider profile | `configs/profiles/environment/wrong-provider.yaml` |\n"
                    "| Software profile | `configs/profiles/software/fixture-software.yaml` |\n"
                    "| Result summary path | `%s` |\n"
                    "Profile IDs: `local-qemu`, `fixture-software`.\n" % (artifact,),
                    provider_prerequisites=(
                        "Local QEMU/libvirt/KVM host with SSH access; "
                        "no cloud credentials."
                    ),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-profile-field-mismatch",
                        "docs/release_evidence_example.md P-QEMU-01 Provider "
                        "profile='configs/profiles/environment/wrong-provider.yaml' "
                        "but certified configs use environment profile(s): local-qemu",
                    )
                ],
            )

    def test_artifact_root_field_must_match_test_results_root(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            wrong_root = root / "other" / ".continuum"
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "| Artifact root | `%s` |\n" % (artifact, wrong_root),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-artifact-root-mismatch",
                        "docs/release_evidence_example.md Artifact root='%s' "
                        "but %s is under %s"
                        % (wrong_root, artifact, artifact.parent.parent),
                    )
                ],
            )

    def test_single_result_evidence_doc_must_have_artifact_root_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    include_artifact_root=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-artifact-root-missing",
                        "docs/release_evidence_example.md has one primary "
                        "test-results artifact %s but no Artifact root field"
                        % (artifact,),
                    )
                ],
            )

    def test_single_result_evidence_doc_must_have_result_summary_path_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "Result summary:\n\n```text\n%s\n```\n" % (artifact,),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-result-summary-path-missing",
                        "docs/release_evidence_example.md has one primary "
                        "test-results artifact %s but no Result summary path field"
                        % (artifact,),
                    )
                ],
            )

    def test_single_result_evidence_doc_must_have_required_artifacts_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Required artifacts checked",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-required-artifacts-field-missing",
                        "docs/release_evidence_example.md has one primary "
                        "test-results artifact %s but no Required artifacts checked field"
                        % (artifact,),
                    )
                ],
            )

    def test_single_result_evidence_doc_required_artifacts_must_name_baseline_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Required artifacts checked | test-results summary |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Required artifacts checked",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-required-artifacts-field-incomplete",
                        "docs/release_evidence_example.md Required artifacts checked="
                        "'test-results summary' is missing: experiment lock, "
                        "state file, stdout artifact, stderr artifact, metadata artifact, "
                        "infrastructure phase evidence",
                    )
                ],
            )

    def test_single_result_evidence_doc_required_artifacts_must_name_teardown_when_claimed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=infrastructure, "
                    "resume_contract_match, teardown_verified"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Required artifacts checked | test-results summary, experiment lock, "
                    "state file, stdout/stderr/metadata artifacts, "
                    "infrastructure phase evidence |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Required artifacts checked",
                    runtime_targets="`infrastructure`, teardown",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-required-artifacts-field-incomplete",
                        "docs/release_evidence_example.md Required artifacts checked="
                        "'test-results summary, experiment lock, state file, "
                        "stdout/stderr/metadata artifacts, infrastructure phase evidence' "
                        "is missing: teardown evidence",
                    )
                ],
            )

    def test_required_artifacts_field_must_name_aggregate_artifact_kinds(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            evidence_path = root / "docs" / "release_evidence_example.md"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Required artifacts checked | test-results summary, experiment lock, "
                "state file, stdout/stderr/metadata artifacts |\n",
                encoding="utf-8",
            )
            artifacts = [
                check_release_evidence_artifacts.EvidenceArtifact(
                    "docs/release_evidence_example.md",
                    evidence_path,
                    root / "logs" / "cloud_static_audit_2026-05-25T000000Z.md",
                    "cloud-static-audit",
                    1,
                ),
                check_release_evidence_artifacts.EvidenceArtifact(
                    "docs/release_evidence_example.md",
                    evidence_path,
                    root / "logs" / "netperf_results.ndjson",
                    "network-ndjson",
                    2,
                ),
                check_release_evidence_artifacts.EvidenceArtifact(
                    "docs/release_evidence_example.md",
                    evidence_path,
                    root / "logs" / "fixture_metrics_manifest.json",
                    "benchmark-metrics-manifest",
                    3,
                ),
            ]

            check_required_artifacts = getattr(
                check_release_evidence_artifacts,
                "_check_evidence_doc_required_artifact_fields",
            )
            self.assertEqual(
                check_required_artifacts(artifacts),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-required-artifacts-field-incomplete",
                        "docs/release_evidence_example.md Required artifacts checked="
                        "'test-results summary, experiment lock, state file, "
                        "stdout/stderr/metadata artifacts' is missing: "
                        "cloud-static audit report, network NDJSON artifact, "
                        "benchmark metrics manifest",
                    )
                ],
            )

    def test_required_artifacts_field_must_not_claim_absent_artifact_kinds(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            evidence_path = root / "docs" / "release_evidence_example.md"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Required artifacts checked | test-results summary, experiment lock, "
                "state file, stdout/stderr/metadata artifacts, cloud-static audit report |\n",
                encoding="utf-8",
            )
            artifacts = [
                check_release_evidence_artifacts.EvidenceArtifact(
                    "docs/release_evidence_example.md",
                    evidence_path,
                    root
                    / "artifacts"
                    / ".continuum"
                    / "test_results"
                    / "test_results_2026-05-23_18-35-48.json",
                    "test-results",
                    1,
                )
            ]

            check_required_artifacts = getattr(
                check_release_evidence_artifacts,
                "_check_evidence_doc_required_artifact_fields",
            )
            self.assertEqual(
                check_required_artifacts(artifacts),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-required-artifacts-field-overclaimed",
                        "docs/release_evidence_example.md Required artifacts checked="
                        "'test-results summary, experiment lock, state file, "
                        "stdout/stderr/metadata artifacts, cloud-static audit report' "
                        "claims absent artifact kind(s): cloud-static audit report",
                    )
                ],
            )

    def test_required_artifacts_field_must_name_runtime_phase_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=application, "
                    "resume_contract_match"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Required artifacts checked | test-results summary, experiment lock, "
                    "state file, stdout/stderr/metadata artifacts |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Required artifacts checked",
                    runtime_targets="`infrastructure`, `software`, `application`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-required-artifacts-field-incomplete",
                        "docs/release_evidence_example.md Required artifacts checked="
                        "'test-results summary, experiment lock, state file, "
                        "stdout/stderr/metadata artifacts' is missing: "
                        "infrastructure phase evidence, software phase evidence, "
                        "application phase evidence",
                    )
                ],
            )

    def test_single_result_evidence_doc_result_summary_path_must_match_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            wrong_path = artifact.parent / "wrong_summary.json"
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Result summary:\n\n```text\n%s\n```\n" % (wrong_path, artifact),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-result-summary-path-mismatch",
                        "docs/release_evidence_example.md Result summary path='%s' "
                        "but primary test-results artifact is %s"
                        % (wrong_path, artifact),
                    )
                ],
            )

    def test_cleanup_runtime_target_requires_teardown_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Required artifacts checked | test-results summary, experiment lock, "
                    "state file, stdout/stderr/metadata artifacts, "
                    "infrastructure phase evidence, teardown evidence |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Required artifacts checked",
                    runtime_targets="`infrastructure`, cleanup",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-cleanup-claim-missing-teardown-evidence",
                        "docs/release_evidence_example.md Runtime targets="
                        "'`infrastructure`, cleanup' claims cleanup/teardown but "
                        "no retained test-results success_reason includes "
                        "teardown_verified",
                    )
                ],
            )

    def test_cleanup_runtime_target_passes_with_teardown_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, "
                    "state_file_written, state_phase=infrastructure, "
                    "resume_contract_match, teardown_verified"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Required artifacts checked | test-results summary, experiment lock, "
                    "state file, stdout/stderr/metadata artifacts, "
                    "infrastructure phase evidence, teardown evidence |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Required artifacts checked",
                    runtime_targets="`infrastructure`, teardown",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_test_results_summary_must_record_top_level_provenance(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            payload.pop("timestamp")
            payload["artifacts_dir"] = str(root / "missing-results-dir")
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-timestamp-missing",
                        "%s has no timestamp" % (artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-artifacts-dir-missing",
                        "%s references missing artifacts_dir %s"
                        % (artifact, root / "missing-results-dir"),
                    ),
                ],
            )

    def test_test_results_summary_timestamp_must_match_filename(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            payload["timestamp"] = "2026-05-23_18-35-49"
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-timestamp-mismatch",
                        "%s timestamp='2026-05-23_18-35-49' expected "
                        "'2026-05-23_18-35-48' from filename" % (artifact,),
                    )
                ],
            )

    def test_test_results_entry_artifacts_must_stay_under_artifacts_dir(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            outside_dir = root / "outside"
            outside_dir.mkdir()
            outside_stdout = outside_dir / "stdout.txt"
            outside_stdout.write_text("outside stdout\n", encoding="utf-8")
            payload["results"][0]["stdout_artifact"] = str(outside_stdout)
            metadata_artifact = Path(payload["results"][0]["metadata_artifact"])
            metadata_artifact.write_text(json.dumps(payload["results"][0]), encoding="utf-8")
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-artifact-outside-artifacts-dir",
                        "%s results[0] stdout_artifact=%s is outside artifacts_dir %s"
                        % (artifact, outside_stdout, artifact.with_suffix("")),
                    )
                ],
            )

    def test_evidence_doc_must_mention_certified_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "The exact config path is intentionally omitted here.\n" % (artifact,),
                    mentioned_config_path=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-config-not-mentioned",
                        "docs/release_evidence_example.md P-QEMU-01 does not mention "
                        "certified config configs/experiments/parity/qemu/01.yaml",
                    )
                ],
            )

    def test_single_config_evidence_doc_must_have_config_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "This evidence certifies matrix row P-QEMU-01 and config %s.\n"
                    % (artifact, config_path),
                    mentioned_config_path=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-config-field-missing",
                        "docs/release_evidence_example.md references config %s "
                        "but has no Config field" % (config_path,),
                    )
                ],
            )

    def test_single_config_evidence_doc_config_field_must_match_matrix(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            self._write_matrix(root, config_path=config_path)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            wrong_config = "configs/experiments/parity/qemu/wrong.yaml"
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Config | `%s` |\n"
                    "| Result summary path | `%s` |\n"
                    "This evidence certifies matrix row P-QEMU-01 and config %s.\n"
                    % (wrong_config, artifact, config_path),
                    mentioned_config_path=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-config-field-mismatch",
                        "docs/release_evidence_example.md Config='%s' but matrix "
                        "references config %s" % (wrong_config, config_path),
                    )
                ],
            )

    def test_evidence_doc_must_mention_ready_matrix_row_id(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    matrix_row_id=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-row-id-not-mentioned",
                        "docs/release_evidence_example.md does not mention ready "
                        "matrix row P-QEMU-01",
                    )
                ],
            )

    def test_ready_row_id_mention_must_not_match_subset_prefix(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "This evidence mentions only P-QEMU-01-SW.\n" % (artifact,),
                    matrix_row_id=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-row-id-not-mentioned",
                        "docs/release_evidence_example.md does not mention ready "
                        "matrix row P-QEMU-01",
                    )
                ],
            )

    def test_matrix_row_id_field_must_match_referencing_ready_row(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "This evidence certifies matrix row P-QEMU-01.\n" % (artifact,),
                    matrix_row_id="P-QEMU-02",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-matrix-row-id-mismatch",
                        "docs/release_evidence_example.md Matrix row ID='P-QEMU-02' "
                        "but matrix references rows: P-QEMU-01",
                    )
                ],
            )

    def test_matrix_row_id_field_accepts_milestone_row_ids(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu_kubecontrol_empty/01.yaml"
            evidence_doc = "docs/release_evidence_example.md"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| M2-QEMU-KUBECONTROL-TRACE | `%s` | `certified` | Evidence: `%s`. |\n"
                % (config_path, evidence_doc),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            self._write_config_targets(root, config_path=config_path)
            (root / evidence_doc).write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "This evidence certifies matrix row M2-QEMU-KUBECONTROL-TRACE.\n"
                    % (artifact,),
                    matrix_row_id="M2-QEMU-KUBECONTROL-TRACE",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_single_result_evidence_doc_must_have_matrix_row_id_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "This evidence certifies matrix row P-QEMU-01.\n" % (artifact,),
                    matrix_row_id=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-matrix-row-id-missing",
                        "docs/release_evidence_example.md references rows P-QEMU-01 "
                        "but has no Matrix row ID field",
                    )
                ],
            )

    def test_suite_field_must_match_referencing_ready_row_suite(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `%s` | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n" % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Suite | `wrong_suite` |\n"
                    "| Result summary path | `%s` |\n"
                    "Command: sudo -n -u continuum-smoke /usr/local/bin/"
                    "run-continuum-smoke qemu_infra_parity\n" % (artifact,),
                    matrix_row_id="P-QEMU-01",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-suite-field-mismatch",
                        "docs/release_evidence_example.md Suite='wrong_suite' "
                        "but matrix references suites: qemu_infra_parity",
                    )
                ],
            )

    def test_single_suite_evidence_doc_must_have_suite_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `%s` | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n" % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            command = (
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_infra_parity"
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Command | `%s` |\n"
                    "| Result summary path | `%s` |\n" % (command, artifact),
                    matrix_row_id="P-QEMU-01",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-suite-field-missing",
                        "docs/release_evidence_example.md suite qemu_infra_parity "
                        "has one primary test-results artifact but no Suite field",
                    )
                ],
            )

    def test_single_suite_evidence_doc_must_have_command_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `%s` | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n" % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Suite | `qemu_infra_parity` |\n"
                    "| Result summary path | `%s` |\n"
                    "\nCommand:\n\n```bash\n"
                    "sudo -n -u continuum-smoke /usr/local/bin/"
                    "run-continuum-smoke qemu_infra_parity\n```\n" % (artifact,),
                    omitted_context_field="Command",
                    matrix_row_id="P-QEMU-01",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-command-field-missing",
                        "docs/release_evidence_example.md suite qemu_infra_parity "
                        "has one primary test-results artifact but no Command field",
                    )
                ],
            )

    def test_single_suite_evidence_doc_command_field_must_match_suite(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `%s` | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n" % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, config_path=config_path)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Suite | `qemu_infra_parity` |\n"
                    "| Result summary path | `%s` |\n"
                    "Command: sudo -n -u continuum-smoke /usr/local/bin/"
                    "run-continuum-smoke qemu_infra_parity\n" % (artifact,),
                    matrix_row_id="P-QEMU-01",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-command-field-mismatch",
                        "docs/release_evidence_example.md Command='fixture command' "
                        "but suite qemu_infra_parity expects 'sudo -n -u "
                        "continuum-smoke /usr/local/bin/run-continuum-smoke "
                        "qemu_infra_parity'",
                    )
                ],
            )

    def test_each_evidence_doc_must_name_a_primary_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `configs/experiments/parity/qemu/01.yaml` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
                "| M1-CORE | core | `core-ready` | "
                "Evidence: `docs/release_evidence_empty.md`. |\n",
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    runtime_targets="`infrastructure`, `software`",
                ),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_empty.md").write_text(
                self._evidence_text(
                    "This document intentionally has no artifact path.\n",
                    mentioned_config_path=None,
                    matrix_row_id="M1-CORE",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-primary-artifact-missing",
                        "docs/release_evidence_empty.md names no primary artifact path",
                    )
                ],
            )

    def test_evidence_doc_records_ready_row_suite_command(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `%s` | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n" % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            command = (
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_infra_parity"
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Command | `%s` |\n"
                    "| Suite | `qemu_infra_parity` |\n"
                    "| Result summary path | `%s` |\n" % (command, artifact),
                    omitted_context_field="Command",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_ready_row_suite_command_must_be_recorded_in_evidence_doc(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `%s` | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n" % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-command-missing-for-suite",
                        "docs/release_evidence_example.md P-QEMU-01 uses suite "
                        "qemu_infra_parity but evidence does not record 'sudo -n -u "
                        "continuum-smoke /usr/local/bin/run-continuum-smoke "
                        "qemu_infra_parity'",
                    )
                ],
            )

    def test_ready_row_suite_command_mapping_must_exist(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | suite `custom_cert_suite` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n",
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-suite-wrapper-unknown",
                        "docs/release_evidence_example.md P-QEMU-01 uses suite "
                        "custom_cert_suite but no wrapper command mapping exists",
                    )
                ],
            )

    def test_evidence_doc_mentions_ready_row_wrapper_scenario(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Scenario | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | wrapper scenario `infra_one_vm` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n",
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Wrapper scenario | `infra_one_vm` |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    mentioned_config_path=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_ready_row_wrapper_scenario_must_be_recorded_in_evidence_doc(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Scenario | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | wrapper scenario `infra_one_vm` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n",
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    mentioned_config_path=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-wrapper-scenario-missing",
                        "docs/release_evidence_example.md P-QEMU-01 uses wrapper scenario "
                        "infra_one_vm but evidence does not mention it",
                    )
                ],
            )

    def test_subset_evidence_must_name_parent_noncertification_scope(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01-SW | `%s` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
                % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Matrix row ID: `P-QEMU-01-SW`\n\n"
                    "This evidence does not certify image-classification "
                    "metric artifacts.\n" % (artifact,),
                    matrix_row_id="P-QEMU-01-SW",
                    runtime_targets="`infrastructure`, `software`",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-subset-parent-scope-missing",
                        "docs/release_evidence_example.md P-QEMU-01-SW must state "
                        "that it does not certify parent row P-QEMU-01",
                    )
                ],
            )

    def test_subset_evidence_runtime_targets_must_include_software(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01-SW | `%s` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
                % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n\n"
                    "This evidence does not certify parent row P-QEMU-01.\n"
                    "This evidence does not certify image-classification "
                    "metric artifacts.\n" % (artifact,),
                    runtime_targets="`infrastructure`",
                    matrix_row_id="P-QEMU-01-SW",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-subset-runtime-missing-software",
                        "docs/release_evidence_example.md P-QEMU-01-SW is a "
                        "software-only subset row but Runtime targets does not "
                        "include software",
                    )
                ],
            )

    def test_subset_evidence_runtime_targets_must_not_include_application(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01-SW | `%s` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
                % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n\n"
                    "This evidence does not certify parent row P-QEMU-01.\n"
                    "This evidence does not certify image-classification "
                    "metric artifacts.\n" % (artifact,),
                    runtime_targets="`infrastructure`, `software`, `application`",
                    matrix_row_id="P-QEMU-01-SW",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-subset-runtime-includes-application",
                        "docs/release_evidence_example.md P-QEMU-01-SW is a subset "
                        "row but Runtime targets includes application",
                    )
                ],
            )

    def test_subset_evidence_must_exclude_image_classification_metric_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01-SW | `%s` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n"
                % (config_path,),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n\n"
                    "This evidence does not certify parent row P-QEMU-01.\n" % (artifact,),
                    runtime_targets="`infrastructure`, `software`",
                    matrix_row_id="P-QEMU-01-SW",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-subset-metric-scope-missing",
                        "docs/release_evidence_example.md P-QEMU-01-SW must state "
                        "that image-classification metric artifacts are not certified "
                        "by the software-only subset evidence",
                    )
                ],
            )

    def test_evidence_doc_requires_source_context(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Git commit",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-context-field-missing",
                        "docs/release_evidence_example.md missing Git commit",
                    )
                ],
            )

    def test_evidence_doc_requires_hex_git_commit(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    git_commit="not-a-commit",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-git-commit-invalid",
                        "docs/release_evidence_example.md Git commit='not-a-commit' "
                        "is not a 7-40 character hexadecimal commit",
                    )
                ],
            )

    def test_single_result_evidence_doc_must_have_runner_context_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Runner user | `continuum-smoke` |\n"
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Runner context",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-runner-context-field-missing",
                        "docs/release_evidence_example.md has one primary "
                        "test-results artifact %s but no Runner context field"
                        % (artifact,),
                    )
                ],
            )

    def test_evidence_docs_may_use_distinct_clean_source_commits(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/parity/qemu/01.yaml"
            evidence_doc_a = "docs/release_evidence_a.md"
            evidence_doc_b = "docs/release_evidence_b.md"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Config | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | `%s` | `certified` | Evidence: `%s`. |\n"
                "| P-QEMU-02 | `%s` | `certified` | Evidence: `%s`. |\n"
                % (config_path, evidence_doc_a, config_path, evidence_doc_b),
                encoding="utf-8",
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / evidence_doc_a).write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    git_commit="abcdef0",
                    matrix_row_id="P-QEMU-01",
                ),
                encoding="utf-8",
            )
            (root / evidence_doc_b).write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    git_commit="1234567",
                    matrix_row_id="P-QEMU-02",
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_evidence_doc_requires_iso_date(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    date="23-05-2026",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-date-invalid",
                        "docs/release_evidence_example.md Date='23-05-2026' must use YYYY-MM-DD",
                    )
                ],
            )

    def test_test_results_date_must_match_evidence_doc_date(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    date="2026-05-24",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-date-evidence-date-mismatch",
                        "docs/release_evidence_example.md references %s dated "
                        "2026-05-23 but evidence Date=2026-05-24" % (artifact,),
                    )
                ],
            )

    def test_dated_evidence_doc_date_must_match_filename(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            evidence_doc = "docs/release_evidence_example_2026-05-24.md"
            self._write_matrix(
                root,
                config_path="configs/experiments/parity/qemu/01.yaml",
                evidence_doc=evidence_doc,
            )
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / evidence_doc).write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    date="2026-05-23",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-date-filename-mismatch",
                        "docs/release_evidence_example_2026-05-24.md Date='2026-05-23' "
                        "does not match filename date 2026-05-24",
                    )
                ],
            )

    def test_evidence_doc_requires_limitations_scope(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    include_limitations=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-limitations-missing",
                        "docs/release_evidence_example.md missing limitations or "
                        "non-certification scope",
                    )
                ],
            )

    def test_evidence_doc_requires_runtime_scope(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    include_runtime_scope=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-runtime-scope-missing",
                        "docs/release_evidence_example.md missing Runtime targets field",
                    )
                ],
            )

    def test_state_phase_text_does_not_replace_runtime_targets_field(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "The retained summary recorded `state_phase=infrastructure`.\n"
                    % (artifact,),
                    include_runtime_scope=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-runtime-scope-missing",
                        "docs/release_evidence_example.md missing Runtime targets field",
                    )
                ],
            )

    def test_evidence_doc_requires_provider_host_prerequisites(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/01.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    omitted_context_field="Provider / host prerequisites",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-prerequisites-missing",
                        "docs/release_evidence_example.md missing Provider / host prerequisites",
                    )
                ],
            )

    def test_certified_row_config_must_appear_in_test_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root, config_path="configs/experiments/parity/qemu/expected.yaml")
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (artifact,),
                    mentioned_config_path="configs/experiments/parity/qemu/expected.yaml",
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "evidence-doc-config-not-run",
                        "docs/release_evidence_example.md P-QEMU-01 expected "
                        "configs/experiments/parity/qemu/expected.yaml in retained test-results",
                    )
                ],
            )

    def test_nonready_row_action_text_does_not_create_ready_claim(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Legacy Row | Old Public Surface | Related Rework YAML / Profile | "
                "Status | Certification Action |\n"
                "| --- | --- | --- | --- | --- | --- |\n"
                "| P-QEMU-01 | legacy | surface | "
                "`configs/experiments/parity/qemu/expected.yaml` | "
                "`ported-unverified` | Do not mark `certified` until VM evidence exists. |\n",
                encoding="utf-8",
            )
            self.assertEqual(check_release_evidence_artifacts.iter_ready_row_claims(root), [])

    def test_artifact_audit_summary_count_must_match_extracted_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "| Primary artifacts checked | 2 |\n" % (artifact,)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "artifact-audit-summary-mismatch",
                        "docs/release_evidence_example.md Primary artifacts checked='2' "
                        "expected '1'",
                    )
                ],
            )

    def test_artifact_audit_summary_section_requires_summary_fields(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n\n"
                    "Local release-evidence artifact audit on the certification host:\n\n"
                    "| Field | Value |\n"
                    "| --- | --- |\n"
                    "| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit` |\n"
                    "| Result | `TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0` |\n"
                    % (artifact,)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "artifact-audit-summary-field-missing",
                        "docs/release_evidence_example.md missing Primary artifacts checked",
                    )
                ],
            )

    def test_artifact_audit_summary_command_is_section_scoped(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n\n"
                    "Local release-evidence artifact audit on the certification host:\n\n"
                    "| Field | Value |\n"
                    "| --- | --- |\n"
                    "| Command | `wrong command` |\n"
                    "| Primary artifacts checked | 1 |\n"
                    "| Result | `TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0` |\n"
                    % (artifact,)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "artifact-audit-summary-mismatch",
                        "docs/release_evidence_example.md Command='wrong command' "
                        "expected 'sudo -n -u continuum-smoke "
                        "/usr/local/bin/run-continuum-smoke release-artifact-audit'",
                    )
                ],
            )

    def test_artifact_audit_summary_result_must_match_issue_count(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "| Result | TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=1 |\n" % (artifact,)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "artifact-audit-summary-mismatch",
                        "docs/release_evidence_example.md Result="
                        "'TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=1' expected "
                        "'TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0'",
                    )
                ],
            )

    def test_failed_test_results_artifact_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact, failed=1)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            issues = check_release_evidence_artifacts.find_artifact_issues(root)

            self.assertIn(
                check_release_evidence_artifacts.EvidenceArtifactIssue(
                    "test-results-failed",
                    "%s failed=1" % (artifact,),
                ),
                issues,
            )

    def test_test_results_success_reason_must_include_runtime_markers(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(
                artifact,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, state_file_written, "
                    "state_phase=infrastructure"
                ),
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-success-reason-missing-token",
                        "%s results[0] success_reason missing resume_contract_match"
                        % (artifact,),
                    )
                ],
            )

    def test_test_results_entry_must_record_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            payload["results"][0].pop("config_path")
            payload["results"][0].pop("start_time")
            payload["results"][0]["execution_time"] = -1
            payload["results"][0]["timed_out"] = True
            payload["results"][0]["base_images_rebuilt"] = "not-a-list"
            payload["results"][0]["parameter_overrides"] = "not-a-mapping"
            metadata_artifact = Path(payload["results"][0]["metadata_artifact"])
            metadata_artifact.write_text(json.dumps(payload["results"][0]), encoding="utf-8")
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-config-path-missing",
                        "%s results[0] has no config_path" % (artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-start-time-missing",
                        "%s results[0] has no start_time" % (artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-execution-time-invalid",
                        "%s results[0] execution_time=-1" % (artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-timed-out",
                        "%s results[0] timed_out=True" % (artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-base-images-invalid",
                        "%s results[0] base_images_rebuilt='not-a-list'" % (artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-parameter-overrides-invalid",
                        "%s results[0] parameter_overrides='not-a-mapping'" % (artifact,),
                    ),
                ],
            )

    def test_test_results_entry_artifacts_must_exist(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            missing_stdout = payload["results"][0]["stdout_artifact"]
            Path(missing_stdout).unlink()
            payload["results"][0].pop("stderr_artifact")
            metadata_artifact = Path(payload["results"][0]["metadata_artifact"])
            metadata_artifact.write_text(json.dumps(payload["results"][0]), encoding="utf-8")
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-artifact-missing",
                        "%s results[0] stdout_artifact references missing %s"
                        % (artifact, missing_stdout),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-artifact-field-missing",
                        "%s results[0] has no stderr_artifact" % (artifact,),
                    ),
                ],
            )

    def test_test_results_metadata_artifact_must_be_valid_json_mapping(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            metadata_artifact = Path(payload["results"][0]["metadata_artifact"])
            metadata_artifact.write_text("not-json", encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            issues = check_release_evidence_artifacts.find_artifact_issues(root)

            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0].kind, "test-results-entry-metadata-json-invalid")
            self.assertIn(str(metadata_artifact), issues[0].detail)

    def test_test_results_metadata_artifact_must_match_summary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(artifact)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            metadata_artifact = Path(payload["results"][0]["metadata_artifact"])
            metadata = json.loads(metadata_artifact.read_text(encoding="utf-8"))
            metadata["config_path"] = "configs/experiments/parity/qemu/other.yaml"
            metadata_artifact.write_text(json.dumps(metadata), encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Result summary path | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "test-results-entry-metadata-mismatch",
                        "%s results[0] metadata config_path="
                        "'configs/experiments/parity/qemu/other.yaml' expected "
                        "'configs/experiments/parity/qemu/01.yaml'" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_required_gate_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text(failing_gate="unit unittest discovery")
                + self._release_readiness_text(),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-required-gate-failed",
                        "%s: - unit unittest discovery: FAIL (1)" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_summary_counts_match_evidence_doc(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            marker_line = "- " + "TO" + "DO/" + "FIX" + "ME debt scan: MATCHES FOUND (2)\n"
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + "## Informational Checks\n"
                + "- release evidence artifact audit: OK\n"
                + "- M1 pre-tag readiness check: FINDINGS OR UNAVAILABLE (1)\n"
                + marker_line
                + "\n"
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
                "### unit unittest discovery\n"
                "Ran 3 tests in 0.1s\n"
                "### e2e unittest discovery\n"
                "Ran 2 tests in 0.1s\n"
                "### combined unittest discovery\n"
                "Ran 5 tests in 0.2s\n"
                "### combined pytest suite\n"
                "5 passed in 0.3s\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Report | `%s` |\n"
                    "| Unit unittest discovery | 3 tests OK |\n"
                    "| E2E unittest discovery | 2 tests OK |\n"
                    "| Combined unittest discovery | 5 tests OK |\n"
                    "| Pytest mirror | 5 passed |\n"
                    "| Marker debt scan | MATCHES FOUND (2) |\n" % (artifact,)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [],
            )

    def test_cloud_static_audit_records_ready_suite_prereqs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n",
                encoding="utf-8",
            )
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text()
                + "## Commands Executed\n"
                "1. python3 -B scripts/test/run_tests.py --check-prereqs "
                "--suite qemu_infra_parity\n",
                encoding="utf-8",
            )
            command = (
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_infra_parity"
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Command | `%s` |\n| Report | `%s` |\n" % (command, artifact)
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_cloud_static_audit_records_all_parity_suite_prereqs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            (root / "scripts" / "test").mkdir(parents=True)
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps(
                    {
                        "test_suites": {
                            "qemu_infra_parity": {
                                "directories": ["configs/experiments/parity/qemu/"]
                            },
                            "smoke": {
                                "directories": ["configs/experiments/smoke/"]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text()
                + "## Commands Executed\n"
                "1. python3 -B scripts/test/run_tests.py --check-prereqs "
                "--suite qemu_infra_parity\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_cloud_static_audit_must_record_all_parity_suite_prereqs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            (root / "scripts" / "test").mkdir(parents=True)
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps(
                    {
                        "test_suites": {
                            "qemu_infra_parity": {
                                "directories": ["configs/experiments/parity/qemu/"]
                            },
                            "qemu_k8s_image_parity": {
                                "directories": [
                                    "configs/experiments/parity/qemu_k8s_image/"
                                ]
                            },
                            "smoke": {
                                "directories": ["configs/experiments/smoke/"]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text()
                + "## Commands Executed\n"
                "1. python3 -B scripts/test/run_tests.py --check-prereqs "
                "--suite qemu_infra_parity\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-parity-suite-prereq-missing",
                        "%s missing --check-prereqs coverage for parity suite "
                        "qemu_k8s_image_parity" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_accepts_registry_cache_preflight_for_parity_suite(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| M2-QEMU-KUBECONTROL-EMPTY | suite `qemu_kubecontrol_empty_parity` | "
                "`certified` | Evidence: `docs/release_evidence_example.md`. |\n",
                encoding="utf-8",
            )
            (root / "scripts" / "test").mkdir(parents=True)
            (root / "scripts" / "test" / "test_config.json").write_text(
                json.dumps(
                    {
                        "test_suites": {
                            "qemu_kubecontrol_empty_parity": {
                                "directories": [
                                    "configs/experiments/parity/qemu_kubecontrol_empty/"
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            readiness_text = self._release_readiness_text(
                infra_prereq_status=None,
            ).replace(
                "## Output Excerpts\n",
                "- QEMU kubecontrol empty parity suite prerequisites: OK\n\n"
                "## Output Excerpts\n",
            )
            artifact.write_text(
                self._required_gates_text()
                + readiness_text
                + "## Commands Executed\n"
                "1. python3 -B scripts/test/prime_local_registry_cache.py "
                "--suite qemu_kubecontrol_empty_parity --check-only\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubecontrol_empty_parity` |\n"
                    "| Report | `%s` |\n" % (artifact,),
                    matrix_row_id="M2-QEMU-KUBECONTROL-EMPTY",
                    mentioned_config_path=None,
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_cloud_static_audit_must_record_ready_suite_prereqs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n",
                encoding="utf-8",
            )
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text()
                + "## Commands Executed\n"
                "1. python3 -B scripts/test/run_tests.py --list-suites\n",
                encoding="utf-8",
            )
            command = (
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_infra_parity"
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Command | `%s` |\n| Report | `%s` |\n" % (command, artifact)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-ready-suite-prereq-missing",
                        "%s missing --check-prereqs coverage for ready suite "
                        "qemu_infra_parity" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_requires_ready_suite_prereq_status_ok(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "release_certification_matrix.md").write_text(
                "| ID | Suite | Status | Certification Action |\n"
                "| --- | --- | --- | --- |\n"
                "| P-QEMU-01 | suite `qemu_infra_parity` | `certified` | "
                "Evidence: `docs/release_evidence_example.md`. |\n",
                encoding="utf-8",
            )
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(
                    infra_prereq_status="FINDINGS OR UNAVAILABLE (1)"
                )
                + "## Commands Executed\n"
                "1. python3 -B scripts/test/run_tests.py --check-prereqs "
                "--suite qemu_infra_parity\n",
                encoding="utf-8",
            )
            command = (
                "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
                "qemu_infra_parity"
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Command | `%s` |\n| Report | `%s` |\n" % (command, artifact)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-ready-suite-prereq-status-not-ok",
                        "%s ready suite qemu_infra_parity prereq status QEMU infra "
                        "parity suite prerequisites='FINDINGS OR UNAVAILABLE (1)' "
                        "expected OK" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_summary_count_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text()
                + "### unit unittest discovery\n"
                "Ran 3 tests in 0.1s\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Report | `%s` |\n"
                    "| Unit unittest discovery | 4 tests OK |\n" % (artifact,)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-evidence-summary-mismatch",
                        "docs/release_evidence_example.md Unit unittest discovery="
                        "'4 tests OK' expected '3 tests OK' from %s" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_missing_required_gate_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            omitted_gate = "public release-claims check"
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            required_lines = [
                "## Required Gates\n",
                *(
                    "- %s: PASS\n" % (gate,)
                    for gate in check_release_evidence_artifacts.REQUIRED_CLOUD_AUDIT_GATES
                    if gate != omitted_gate
                ),
                "\n",
            ]
            artifact.write_text(
                "".join(required_lines) + self._release_readiness_text(),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-required-gate-missing",
                        "%s missing required gate %s" % (artifact, omitted_gate),
                    )
                ],
            )

    def test_cloud_static_audit_latest_generated_report_is_accepted(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            report_dir = root / "logs" / "cloud_static_audit"
            report_dir.mkdir(parents=True)
            older_report = report_dir / "cloud_static_audit_2026-05-23T000000Z.md"
            latest_report = report_dir / "cloud_static_audit_2026-05-23T001000Z.md"
            report_text = self._required_gates_text() + self._release_readiness_text()
            older_report.write_text(report_text, encoding="utf-8")
            latest_report.write_text(report_text, encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (latest_report,)),
                encoding="utf-8",
            )

            self.assertEqual(check_release_evidence_artifacts.find_artifact_issues(root), [])

    def test_cloud_static_audit_must_reference_latest_generated_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            report_dir = root / "logs" / "cloud_static_audit"
            report_dir.mkdir(parents=True)
            older_report = report_dir / "cloud_static_audit_2026-05-23T000000Z.md"
            latest_report = report_dir / "cloud_static_audit_2026-05-23T001000Z.md"
            report_text = self._required_gates_text() + self._release_readiness_text()
            older_report.write_text(report_text, encoding="utf-8")
            latest_report.write_text(report_text, encoding="utf-8")
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (older_report,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-report-not-latest",
                        "docs/release_evidence_example.md references %s but latest "
                        "cloud audit report is %s" % (older_report, latest_report),
                    )
                ],
            )

    def test_cloud_static_audit_requires_pretag_readiness_informational_check(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(include_pretag_status=False),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-informational-check-missing",
                        "%s missing informational check M1 pre-tag readiness check"
                        % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_requires_artifact_audit_informational_check(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(include_artifact_status=False),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-informational-check-missing",
                        "%s missing informational check release evidence artifact audit"
                        % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_requires_parseable_artifact_audit_total(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(include_artifact_total=False),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-artifact-audit-total-missing",
                        "%s missing TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES output"
                        % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_rejects_nonzero_artifact_audit_total(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text() + self._release_readiness_text(artifact_total=1),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-artifact-audit-total-nonzero",
                        "%s TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=1 expected 0"
                        % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_requires_release_zero_totals(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(include_claim_total=False),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-zero-total-missing",
                        "%s missing TOTAL_RELEASE_CLAIM_ISSUES output" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_rejects_nonzero_release_totals(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(docs_total=2, matrix_total=1),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-zero-total-nonzero",
                        "%s TOTAL_MISSING_REFERENCES=2 expected 0" % (artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-zero-total-nonzero",
                        "%s TOTAL_RELEASE_MATRIX_ISSUES=1 expected 0" % (artifact,),
                    ),
                ],
            )

    def test_cloud_static_audit_requires_parseable_pretag_total(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(include_pretag_total=False),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-pretag-total-missing",
                        "%s missing TOTAL_RELEASE_PRETAG_ISSUES output" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_pretag_ok_requires_zero_total(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(pretag_status="OK", pretag_total=1),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-pretag-status-total-mismatch",
                        "%s M1 pre-tag readiness check='OK' but "
                        "TOTAL_RELEASE_PRETAG_ISSUES=1" % (artifact,),
                    )
                ],
            )

    def test_cloud_static_audit_pretag_findings_requires_nonzero_total(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            artifact = root / "logs" / "cloud_static_audit_2026-05-23T000000Z.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                self._required_gates_text()
                + self._release_readiness_text(
                    pretag_status="FINDINGS OR UNAVAILABLE (1)",
                    pretag_total=0,
                ),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text("| Report | `%s` |\n" % (artifact,)),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "cloud-audit-pretag-status-total-mismatch",
                        "%s M1 pre-tag readiness check='FINDINGS OR UNAVAILABLE (1)' "
                        "but TOTAL_RELEASE_PRETAG_ISSUES=0" % (artifact,),
                    )
                ],
            )

    def test_benchmark_manifest_requires_existing_nonempty_tables(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            result_summary = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            table = root / "artifacts" / "metrics.csv"
            table.parent.mkdir(parents=True)
            table.write_text("latency_avg (ms)\n1.0\n", encoding="utf-8")
            manifest = root / "artifacts" / "run_metrics_manifest.json"
            self._write_test_results(
                result_summary,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, state_file_written, "
                    "state_phase=application, resume_contract_match, "
                    "benchmark_metric_artifacts=%s" % (manifest,)
                ),
            )
            manifest.write_text(
                json.dumps(
                    {
                        "kind": "ContinuumBenchmarkMetrics",
                        "tables": [{"path": str(table), "rows": 1}],
                    }
                ),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Latest benchmark metric artifact:\n"
                    "`%s`\n" % (result_summary, manifest)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [],
            )

    def test_specialized_artifact_must_be_linked_from_test_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            result_summary = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            table = root / "artifacts" / "metrics.csv"
            table.parent.mkdir(parents=True)
            table.write_text("latency_avg (ms)\n1.0\n", encoding="utf-8")
            manifest = root / "artifacts" / "run_metrics_manifest.json"
            self._write_test_results(result_summary)
            manifest.write_text(
                json.dumps(
                    {
                        "kind": "ContinuumBenchmarkMetrics",
                        "tables": [{"path": str(table), "rows": 1}],
                    }
                ),
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Latest benchmark metric artifact:\n"
                    "`%s`\n" % (result_summary, manifest)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "specialized-artifact-not-linked-from-test-results",
                        "docs/release_evidence_example.md references %s but no retained "
                        "test-results success_reason names it" % (manifest,),
                    )
                ],
            )

    def test_network_ndjson_requires_json_lines(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_matrix(root)
            result_summary = (
                root
                / "artifacts"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            artifact = root / "artifacts" / "netperf_results_2026-05-23.ndjson"
            artifact.parent.mkdir(parents=True)
            self._write_test_results(
                result_summary,
                success_reason=(
                    "Success: exit_code=0, experiment_lock_written, state_file_written, "
                    "state_phase=infrastructure, resume_contract_match, "
                    "network_validation_results=%s" % (artifact,)
                ),
            )
            artifact.write_text(
                json.dumps(
                    {
                        "source": "cloud",
                        "target": "edge",
                        "direction": "latency",
                        "output": "ok",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Latest validation artifact:\n%s\n" % (result_summary, artifact)
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [],
            )

    def test_certified_network_emulation_requires_network_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/smoke/network_netperf_two_vm.yaml"
            self._write_matrix(
                root,
                config_path=config_path,
                claim_text="Netperf artifact exists for network profile evidence",
            )
            self._write_config_targets(
                root,
                config_path=config_path,
                network_emulation=True,
            )
            result_summary = (
                root
                / "artifacts"
                / "network_netperf_two_vm"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            self._write_test_results(result_summary, config_path=config_path)
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n" % (result_summary,),
                    runtime_targets="`infrastructure`",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "network-emulation-evidence-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/smoke/network_netperf_two_vm.yaml enables "
                        "network emulation but retained evidence does not link or reference "
                        "a same-run network NDJSON artifact",
                    )
                ],
            )

    def test_certified_network_emulation_accepts_same_run_network_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/smoke/network_netperf_two_vm.yaml"
            self._write_matrix(
                root,
                config_path=config_path,
                claim_text="Netperf artifact exists for network profile evidence",
            )
            self._write_config_targets(
                root,
                config_path=config_path,
                network_emulation=True,
            )
            run_root = root / "artifacts" / "network_netperf_two_vm" / ".continuum"
            result_summary = (
                run_root
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            network_artifact = (
                run_root
                / "logs"
                / "network_validation"
                / "netperf_results_2026-05-23_18:35:48.ndjson"
            )
            self._write_test_results(result_summary, config_path=config_path)
            network_artifact.parent.mkdir(parents=True)
            network_artifact.write_text(
                json.dumps(
                    {
                        "source": "cloud",
                        "target": "endpoint",
                        "direction": "throughput",
                        "output": "ok",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Structured netperf artifact:\n%s\n"
                    % (result_summary, network_artifact),
                    runtime_targets="`infrastructure`",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [],
            )

    def test_network_artifact_must_match_retained_run_root(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_path = "configs/experiments/smoke/network_netperf_two_vm.yaml"
            self._write_matrix(
                root,
                config_path=config_path,
                claim_text="Netperf artifact exists for network profile evidence",
            )
            self._write_config_targets(
                root,
                config_path=config_path,
                network_emulation=True,
            )
            result_summary = (
                root
                / "artifacts"
                / "network_netperf_two_vm"
                / ".continuum"
                / "test_results"
                / "test_results_2026-05-23_18-35-48.json"
            )
            network_artifact = (
                root
                / "artifacts"
                / "other_run"
                / ".continuum"
                / "logs"
                / "network_validation"
                / "netperf_results_2026-05-23_18:35:48.ndjson"
            )
            self._write_test_results(result_summary, config_path=config_path)
            network_artifact.parent.mkdir(parents=True)
            network_artifact.write_text(
                json.dumps(
                    {
                        "source": "cloud",
                        "target": "endpoint",
                        "direction": "throughput",
                        "output": "ok",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "docs" / "release_evidence_example.md").write_text(
                self._evidence_text(
                    "| Result summary path | `%s` |\n"
                    "Structured netperf artifact:\n%s\n"
                    % (result_summary, network_artifact),
                    runtime_targets="`infrastructure`",
                    mentioned_config_path=config_path,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                check_release_evidence_artifacts.find_artifact_issues(root),
                [
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "specialized-artifact-not-linked-from-test-results",
                        "docs/release_evidence_example.md references %s but no retained "
                        "test-results success_reason names it" % (network_artifact,),
                    ),
                    check_release_evidence_artifacts.EvidenceArtifactIssue(
                        "network-emulation-evidence-missing",
                        "docs/release_evidence_example.md P-QEMU-01 config "
                        "configs/experiments/smoke/network_netperf_two_vm.yaml enables "
                        "network emulation but retained evidence does not link or reference "
                        "a same-run network NDJSON artifact",
                    ),
                ],
            )


if __name__ == "__main__":
    unittest.main()
