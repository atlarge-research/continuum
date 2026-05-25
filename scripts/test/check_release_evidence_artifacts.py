#!/usr/bin/env python3
"""Check local release evidence artifacts referenced by certification docs."""

# pylint: disable=duplicate-code,too-many-lines

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Optional

import yaml

try:
    from scripts.test.check_release_matrix import (
        PRETAG_WRAPPER_COMMAND_BY_SUITE,
        REQUIRED_CLOUD_AUDIT_GATES,
    )
except ModuleNotFoundError:  # pragma: no cover - used when run as a script path
    from check_release_matrix import PRETAG_WRAPPER_COMMAND_BY_SUITE, REQUIRED_CLOUD_AUDIT_GATES


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = Path("docs/release_certification_matrix.md")
TEST_CONFIG_PATH = Path("scripts/test/test_config.json")
EVIDENCE_DOC_RE = re.compile(r"`(docs/release_evidence_[^`]+\.md)`")
EVIDENCE_DOC_DATE_RE = re.compile(r"release_evidence_[^/]+_(\d{4}-\d{2}-\d{2})\.md$")
CONFIG_PATH_RE = re.compile(
    r"`((?:configs/experiments|configuration/tests)/[^`]+?\.(?:cfg|ya?ml))`"
)
SUITE_REF_RE = re.compile(r"\bsuite\s+`([^`]+)`")
WRAPPER_SCENARIO_RE = re.compile(r"\bwrapper scenario\s+`([^`]+)`")
SUBSET_ROW_RE = re.compile(r"^(P-[A-Z]+-\d+)-(?:SW|SW-LOCAL)$")
ROW_ID_RE = re.compile(r"\b(?:M1-[A-Z0-9-]+|P-[A-Z]+-\d+(?:-[A-Z]+(?:-[A-Z]+)*)?)\b")
STATUS_LABEL_RE = re.compile(r"`([^`]+)`")
ABSOLUTE_PATH_RE = re.compile(r"(/[^`\s]+(?:\.json|\.md|\.ndjson))")
UNITTEST_COUNT_RE = re.compile(r"Ran (\d+) tests")
PYTEST_COUNT_RE = re.compile(r"(\d+) passed")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATE_PHASE_RE = re.compile(r"\bstate_phase=([A-Za-z0-9_-]+)")
BENCHMARK_METRIC_ARTIFACT_RE = re.compile(r"\bbenchmark_metric_artifacts=([^,\s]+)")
NETWORK_VALIDATION_ARTIFACT_RE = re.compile(r"\bnetwork_validation_results=([^,\s]+)")
DOCS_PATH_TOTAL_RE = re.compile(r"TOTAL_MISSING_REFERENCES=(\d+)")
RELEASE_CLAIM_TOTAL_RE = re.compile(r"TOTAL_RELEASE_CLAIM_ISSUES=(\d+)")
RELEASE_MATRIX_TOTAL_RE = re.compile(r"TOTAL_RELEASE_MATRIX_ISSUES=(\d+)")
ARTIFACT_AUDIT_TOTAL_RE = re.compile(r"TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=(\d+)")
PRETAG_TOTAL_RE = re.compile(r"TOTAL_RELEASE_PRETAG_ISSUES=(\d+)")
SUITE_PREREQ_RE = re.compile(r"--check-prereqs\s+--suite\s+([A-Za-z0-9_-]+)\b")
EVIDENCE_REQUIRED_STATUS_LABELS = {"core-ready", "certified"}
REQUIRED_SUCCESS_REASON_TOKENS = (
    "exit_code=0",
    "experiment_lock_written",
    "state_file_written",
    "state_phase=",
    "resume_contract_match",
)
REQUIRED_TEST_RESULT_ARTIFACT_FIELDS = (
    "stdout_artifact",
    "stderr_artifact",
    "metadata_artifact",
)
REQUIRED_TEST_RESULT_METADATA_FIELDS = (
    "config_path",
    "success",
    "exit_code",
    "success_reason",
    "start_time",
    "execution_time",
    "timed_out",
    "base_images_rebuilt",
    "parameter_overrides",
    "stdout_artifact",
    "stderr_artifact",
)
TEST_RESULTS_FILENAME_RE = re.compile(
    r"^test_results_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.json$"
)
REQUIRED_CLOUD_AUDIT_INFORMATIONAL_CHECKS = {
    "release evidence artifact audit": ("OK",),
    "M1 pre-tag readiness check": ("OK", "FINDINGS OR UNAVAILABLE"),
}
REQUIRED_CLOUD_AUDIT_ZERO_TOTALS = (
    ("### docs path reference check", DOCS_PATH_TOTAL_RE, "TOTAL_MISSING_REFERENCES"),
    ("### public release-claims check", RELEASE_CLAIM_TOTAL_RE, "TOTAL_RELEASE_CLAIM_ISSUES"),
    (
        "### release certification matrix check",
        RELEASE_MATRIX_TOTAL_RE,
        "TOTAL_RELEASE_MATRIX_ISSUES",
    ),
)
CLAIMED_STDOUT_MARKERS = (
    (
        "kubernetes-node-ready-runtime-check",
        re.compile(r"\bkubernetes\s+node-ready\s+runtime\s+check\b", re.IGNORECASE),
        ("All nodes are Ready",),
    ),
)
CLOUD_AUDIT_PREREQ_STATUS_TITLE_BY_SUITE = {
    "smoke": "smoke suite prerequisites",
    "benchmark_smoke": "benchmark smoke suite prerequisites",
    "network_validation": "network validation suite prerequisites",
    "qemu_infra_parity": "QEMU infra parity suite prerequisites",
    "qemu_k8s_nobench_parity": "QEMU Kubernetes no-benchmark parity suite prerequisites",
    "qemu_kubeedge_software_parity": "QEMU KubeEdge software parity suite prerequisites",
    "qemu_mist_software_parity": "QEMU Mist software parity suite prerequisites",
    "qemu_endpoint_software_parity": "QEMU endpoint-runtime software parity suite prerequisites",
    "qemu_openfaas_software_parity": "QEMU OpenFaaS software parity suite prerequisites",
}
REQUIRED_EVIDENCE_CONTEXT_FIELDS = ("Git commit", "Tree state", "Date")
ARTIFACT_AUDIT_SUMMARY_MARKER = "local release-evidence artifact audit"
ARTIFACT_AUDIT_COMMAND = "python3 scripts/test/check_release_evidence_artifacts.py"
REQUIRED_ARTIFACT_FIELD_MARKERS = (
    ("test-results summary", ("test-results", "test results")),
    ("experiment lock", ("experiment lock",)),
    ("state file", ("state file",)),
    ("stdout artifact", ("stdout",)),
    ("stderr artifact", ("stderr",)),
    ("metadata artifact", ("metadata",)),
)
REQUIRED_ARTIFACT_KIND_FIELD_MARKERS = {
    "cloud-static-audit": (
        "cloud-static audit report",
        ("cloud-static audit", "cloud static audit"),
    ),
    "network-ndjson": ("network NDJSON artifact", ("network ndjson", "netperf")),
    "benchmark-metrics-manifest": (
        "benchmark metrics manifest",
        ("benchmark metrics manifest", "benchmark metric manifest"),
    ),
}
REQUIRED_RUNTIME_TARGET_FIELD_MARKERS = (
    ("infrastructure", "infrastructure phase evidence", ("infrastructure",)),
    ("software", "software phase evidence", ("software", "node-ready")),
    ("application", "application phase evidence", ("application", "benchmark", "metric")),
)


@dataclass(frozen=True)
class EvidenceArtifact:
    """A local artifact path referenced by a release evidence document."""

    evidence_doc: str
    evidence_path: Path
    path: Path
    kind: str
    line: int


@dataclass(frozen=True)
class EvidenceArtifactIssue:
    """A local evidence artifact validation issue."""

    kind: str
    detail: str


@dataclass(frozen=True)
class EvidenceRowClaim:
    """A certified matrix row and its expected runtime configs."""

    row_id: str
    evidence_doc: str
    config_paths: tuple[str, ...]
    suite_names: tuple[str, ...]
    wrapper_scenarios: tuple[str, ...]
    row_text: str = ""


def _repo_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def iter_evidence_docs(root: Path = ROOT) -> list[str]:
    """Return evidence docs referenced by the release certification matrix."""
    matrix_text = (root / MATRIX_PATH).read_text(encoding="utf-8")
    return sorted(set(EVIDENCE_DOC_RE.findall(matrix_text)))


def _paths_from_line(line: str) -> list[Path]:
    return [Path(match) for match in ABSOLUTE_PATH_RE.findall(line)]


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_field_value(value: str) -> str:
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        return value[1:-1]
    return value


def _primary_status_label(row_text: str) -> str:
    for status_label in STATUS_LABEL_RE.findall(row_text):
        if status_label in EVIDENCE_REQUIRED_STATUS_LABELS:
            return status_label
    return ""


def _row_status_label(cells: list[str]) -> str:
    """Return the status label from a matrix row without scanning action prose."""
    if len(cells) >= 6:
        return _primary_status_label(cells[4])
    for cell in cells[1:-1]:
        status_label = _primary_status_label(cell)
        if status_label:
            return status_label
    return ""


def iter_ready_row_claims(root: Path = ROOT) -> list[EvidenceRowClaim]:
    """Return ready matrix rows with release evidence docs and runtime configs."""
    matrix_text = (root / MATRIX_PATH).read_text(encoding="utf-8")
    claims = []
    for line in matrix_text.splitlines():
        if not line.startswith("| M") and not line.startswith("| P-"):
            continue
        cells = _markdown_cells(line)
        if not cells:
            continue
        status_label = _row_status_label(cells)
        if status_label not in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue
        config_paths = tuple(
            sorted(
                {
                    config_path
                    for config_path in CONFIG_PATH_RE.findall(line)
                    if config_path.startswith("configs/experiments/")
                }
            )
        )
        evidence_docs = EVIDENCE_DOC_RE.findall(line)
        for evidence_doc in evidence_docs:
            claims.append(
                EvidenceRowClaim(
                    row_id=cells[0],
                    evidence_doc=evidence_doc,
                    config_paths=config_paths,
                    suite_names=tuple(sorted(set(SUITE_REF_RE.findall(line)))),
                    wrapper_scenarios=tuple(sorted(set(WRAPPER_SCENARIO_RE.findall(line)))),
                    row_text=line,
                )
            )
    return claims


def _subset_parent_row_id(row_id: str) -> str:
    match = SUBSET_ROW_RE.match(row_id)
    return match.group(1) if match else ""


def _artifact_kind(path: Path) -> str:
    path_text = path.as_posix()
    if path_text.endswith(".ndjson"):
        return "network-ndjson"
    if path_text.endswith("_metrics_manifest.json"):
        return "benchmark-metrics-manifest"
    if "/test_results/test_results_" in path_text and path_text.endswith(".json"):
        return "test-results"
    if "cloud_static_audit_" in path_text and path_text.endswith(".md"):
        return "cloud-static-audit"
    return ""


def extract_primary_artifacts(
    root: Path = ROOT,
    evidence_docs: Optional[list[str]] = None,
) -> list[EvidenceArtifact]:
    """Extract primary local artifact paths from release evidence docs."""
    selected_docs = evidence_docs if evidence_docs is not None else iter_evidence_docs(root)
    artifacts: list[EvidenceArtifact] = []
    seen = set()

    for evidence_doc in selected_docs:
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue

        result_summary_window = 0
        evidence_lines = evidence_path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(evidence_lines, 1):
            if "Result summary:" in line:
                result_summary_window = 4

            paths = _paths_from_line(line)
            for path in paths:
                kind = _artifact_kind(path)
                if not kind:
                    continue

                is_primary = (
                    kind != "test-results"
                    or "PASS" in line
                    or "Result summary path" in line
                    or result_summary_window > 0
                )
                if not is_primary:
                    continue

                key = (evidence_doc, path.as_posix())
                if key in seen:
                    continue
                seen.add(key)
                artifacts.append(
                    EvidenceArtifact(
                        evidence_doc=evidence_doc,
                        evidence_path=evidence_path,
                        path=path,
                        kind=kind,
                        line=line_number,
                    )
                )

            if result_summary_window > 0:
                result_summary_window -= 1

    return artifacts


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as filep:
        return json.load(filep)


def _path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _test_results_filename_timestamp(path: Path) -> Optional[str]:
    match = TEST_RESULTS_FILENAME_RE.match(path.name)
    return match.group(1) if match else None


def _repo_root_for_artifact(artifact: EvidenceArtifact) -> Path:
    if artifact.evidence_path.parent.name == "docs":
        return artifact.evidence_path.parent.parent
    return ROOT


def _expected_state_phase_from_config(
    root: Path,
    config_path: str,
) -> tuple[Optional[str], Optional[EvidenceArtifactIssue]]:
    targets, issue = _config_run_targets_from_file(
        root,
        config_path,
        "test-results-entry",
    )
    if issue:
        return None, issue
    if not targets:
        return None, None
    return targets[-1], None


def _config_run_targets_from_file(
    root: Path,
    config_path: str,
    issue_prefix: str,
) -> tuple[tuple[str, ...], Optional[EvidenceArtifactIssue]]:
    config_file = root / config_path
    if not config_file.is_file():
        return (), None
    try:
        payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return (), EvidenceArtifactIssue(
            "%s-config-yaml-invalid" % (issue_prefix,),
            "%s: %s" % (config_path, exc),
        )
    if not isinstance(payload, dict):
        return (), EvidenceArtifactIssue(
            "%s-config-yaml-invalid" % (issue_prefix,),
            "%s is not a mapping" % (config_path,),
        )
    run = payload.get("run")
    targets = run.get("targets") if isinstance(run, dict) else None
    if not isinstance(targets, list) or not targets:
        return (), EvidenceArtifactIssue(
            "%s-config-targets-invalid" % (issue_prefix,),
            "%s run.targets=%r" % (config_path, targets),
        )
    normalized_targets = []
    for target in targets:
        if not isinstance(target, str) or not target.strip():
            return (), EvidenceArtifactIssue(
                "%s-config-targets-invalid" % (issue_prefix,),
                "%s run.targets=%r" % (config_path, targets),
            )
        normalized_targets.append(target.strip().lower())
    return tuple(normalized_targets), None


def _load_config_yaml(root: Path, config_path: str):
    config_file = root / config_path
    if not config_file.is_file():
        return None
    try:
        return yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _config_has_benchmark_pipeline(root: Path, config_path: str) -> bool:
    payload = _load_config_yaml(root, config_path)
    if not isinstance(payload, dict):
        return False
    benchmark = payload.get("benchmark")
    if not isinstance(benchmark, dict):
        return False
    pipeline = benchmark.get("pipeline")
    return isinstance(pipeline, list) and bool(pipeline)


def _config_uses_network_emulation(root: Path, config_path: str) -> bool:
    payload = _load_config_yaml(root, config_path)
    if not isinstance(payload, dict):
        return False
    infrastructure = payload.get("infrastructure")
    if not isinstance(infrastructure, dict):
        return False
    network = infrastructure.get("network")
    if not isinstance(network, dict):
        return False
    return network.get("emulation") is True


def _config_environment_from_file(
    root: Path,
    config_path: str,
) -> str:
    profiles = _config_use_profiles_from_file(root, config_path)
    return profiles[0] if profiles else ""


def _config_use_profiles_from_file(
    root: Path,
    config_path: str,
) -> tuple[str, ...]:
    profiles = []
    use = _config_use_from_file(root, config_path)
    for field in ("environment", "software"):
        value = use.get(field)
        if isinstance(value, str) and value.strip():
            profiles.append(value.strip().lower())
    return tuple(profiles)


def _config_use_from_file(root: Path, config_path: str) -> dict:
    config_file = root / config_path
    if not config_file.is_file():
        return {}
    try:
        payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(payload, dict):
        return {}
    use = payload.get("use")
    return use if isinstance(use, dict) else {}


def _config_use_profile_from_file(root: Path, config_path: str, field: str) -> str:
    value = _config_use_from_file(root, config_path).get(field)
    return value.strip().lower() if isinstance(value, str) and value.strip() else ""


def _profile_id_mentioned(text: str, profile_id: str) -> bool:
    normalized = text.lower().replace("`", "")
    pattern = r"(?<![a-z0-9_-])%s(?![a-z0-9_-])" % (re.escape(profile_id),)
    return re.search(pattern, normalized) is not None


def _suite_name_mentioned(text: str, suite_name: str) -> bool:
    normalized = text.replace("`", "")
    pattern = r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])" % (re.escape(suite_name),)
    return re.search(pattern, normalized) is not None


def _runtime_target_mentioned(runtime_targets: str, target: str) -> bool:
    normalized_targets = runtime_targets.lower().replace("`", "")
    pattern = r"(?<![a-z0-9_])%s(?![a-z0-9_])" % (re.escape(target),)
    return re.search(pattern, normalized_targets) is not None


def _runtime_target_phases(runtime_targets: str) -> tuple[str, ...]:
    return tuple(
        phase
        for phase in ("infrastructure", "software", "application")
        if _runtime_target_mentioned(runtime_targets, phase)
    )


def _state_phases_from_success_reasons(success_reasons: list[str]) -> set[str]:
    phases = set()
    for success_reason in success_reasons:
        match = STATE_PHASE_RE.search(success_reason)
        if match:
            phases.add(match.group(1).lower())
    return phases


def _check_evidence_doc_runtime_targets_match_configs(
    root: Path,
) -> list[EvidenceArtifactIssue]:
    """Ensure evidence Runtime targets cover certified config run.targets."""
    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        fields = _evidence_table_fields(evidence_path.read_text(encoding="utf-8"))
        runtime_targets = fields.get("Runtime targets", "")
        if not runtime_targets:
            continue
        for config_path in claim.config_paths:
            targets, issue = _config_run_targets_from_file(
                root,
                config_path,
                "evidence-doc",
            )
            if issue:
                issues.append(issue)
                continue
            for target in targets:
                if _runtime_target_mentioned(runtime_targets, target):
                    continue
                issues.append(
                    EvidenceArtifactIssue(
                        "evidence-doc-runtime-target-missing",
                        "%s %s config %s run.targets includes %s but "
                        "Runtime targets=%r does not mention it"
                        % (
                            claim.evidence_doc,
                            claim.row_id,
                            config_path,
                            target,
                            runtime_targets,
                        ),
                    )
                )
    return issues


def _check_evidence_doc_runtime_target_claims_have_support(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure Runtime targets do not claim phases absent from configs/results."""
    config_targets_by_doc: dict[str, set[str]] = {}
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        for config_path in claim.config_paths:
            targets, issue = _config_run_targets_from_file(
                root,
                config_path,
                "evidence-doc",
            )
            if issue:
                continue
            config_targets_by_doc.setdefault(claim.evidence_doc, set()).update(targets)

    success_reasons_by_doc: dict[str, list[str]] = {}
    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        success_reasons_by_doc.setdefault(artifact.evidence_doc, []).extend(
            _artifact_success_reasons(artifact)
        )

    issues = []
    for evidence_doc in iter_evidence_docs(root):
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        fields = _evidence_table_fields(evidence_path.read_text(encoding="utf-8"))
        runtime_targets = fields.get("Runtime targets", "")
        if not runtime_targets:
            continue
        supported_phases = set(config_targets_by_doc.get(evidence_doc, set()))
        if not supported_phases:
            continue
        supported_phases.update(
            _state_phases_from_success_reasons(success_reasons_by_doc.get(evidence_doc, []))
        )
        for phase in _runtime_target_phases(runtime_targets):
            if phase in supported_phases:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-runtime-target-unsupported",
                    "%s Runtime targets=%r claims %s but no certified config "
                    "run.targets or retained state_phase evidence supports it"
                    % (evidence_doc, runtime_targets, phase),
                )
            )
    return issues


def _artifact_results_by_config(
    artifacts: list[EvidenceArtifact],
) -> dict[str, dict[str, list[dict]]]:
    """Return evidence-doc -> config-path -> retained result entries."""
    results_by_doc: dict[str, dict[str, list[dict]]] = {}
    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        try:
            payload = _load_json(artifact.path)
        except (OSError, json.JSONDecodeError):
            continue
        results = payload.get("results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            config_path = result.get("config_path")
            if not isinstance(config_path, str) or not config_path:
                continue
            results_by_doc.setdefault(artifact.evidence_doc, {}).setdefault(
                config_path,
                [],
            ).append(result)
    return results_by_doc


def _benchmark_metric_artifact_path(success_reason: str) -> str:
    match = BENCHMARK_METRIC_ARTIFACT_RE.search(success_reason)
    return match.group(1) if match else ""


def _network_validation_artifact_path(success_reason: str) -> str:
    match = NETWORK_VALIDATION_ARTIFACT_RE.search(success_reason)
    return match.group(1) if match else ""


def _check_benchmark_application_evidence(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure certified benchmark application configs retain metric evidence."""
    results_by_doc = _artifact_results_by_config(artifacts)
    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        evidence_path = root / claim.evidence_doc
        evidence_text = (
            evidence_path.read_text(encoding="utf-8") if evidence_path.exists() else ""
        )
        for config_path in claim.config_paths:
            targets, issue = _config_run_targets_from_file(root, config_path, "evidence-doc")
            if issue or "application" not in targets:
                continue
            if not _config_has_benchmark_pipeline(root, config_path):
                continue
            retained_results = results_by_doc.get(claim.evidence_doc, {}).get(config_path, [])
            success_reasons = [
                result.get("success_reason", "")
                for result in retained_results
                if isinstance(result.get("success_reason"), str)
            ]
            if not success_reasons:
                issues.append(
                    EvidenceArtifactIssue(
                        "benchmark-application-evidence-missing",
                        "%s %s config %s has benchmark application pipeline but no "
                        "retained success_reason" % (claim.evidence_doc, claim.row_id, config_path),
                    )
                )
                continue
            if not any(
                "benchmark_evidence_found" in success_reason
                and "benchmark_metric_tables_found" in success_reason
                and _benchmark_metric_artifact_path(success_reason)
                for success_reason in success_reasons
            ):
                issues.append(
                    EvidenceArtifactIssue(
                        "benchmark-application-evidence-missing",
                        "%s %s config %s has benchmark application pipeline but "
                        "retained success_reason lacks benchmark metric evidence markers"
                        % (claim.evidence_doc, claim.row_id, config_path),
                    )
                )
                continue
            for success_reason in success_reasons:
                manifest_path_text = _benchmark_metric_artifact_path(success_reason)
                if not manifest_path_text:
                    continue
                manifest_path = Path(manifest_path_text)
                if not manifest_path.is_file():
                    issues.append(
                        EvidenceArtifactIssue(
                            "benchmark-application-manifest-missing",
                            "%s %s config %s references missing benchmark manifest %s"
                            % (
                                claim.evidence_doc,
                                claim.row_id,
                                config_path,
                                manifest_path_text,
                            ),
                        )
                    )
                if manifest_path_text not in evidence_text:
                    issues.append(
                        EvidenceArtifactIssue(
                            "benchmark-application-manifest-not-mentioned",
                            "%s %s config %s retained benchmark manifest %s is not "
                            "mentioned in evidence"
                            % (
                                claim.evidence_doc,
                                claim.row_id,
                                config_path,
                                manifest_path_text,
                            ),
                        )
                    )
    return issues


def _continuum_root_from_result(result: dict) -> Optional[Path]:
    for field in ("stdout_artifact", "stderr_artifact", "metadata_artifact"):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value)
        try:
            continuum_index = path.parts.index(".continuum")
        except ValueError:
            continue
        return Path(*path.parts[: continuum_index + 1])
    return None


def _artifact_is_under_result_continuum_root(result: dict, artifact_path: Path) -> bool:
    continuum_root = _continuum_root_from_result(result)
    if continuum_root is None:
        return False
    return _path_is_under(artifact_path, continuum_root)


def _check_network_emulation_evidence(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure certified network-emulation configs retain structured netperf evidence."""
    results_by_doc = _artifact_results_by_config(artifacts)
    network_artifacts_by_doc: dict[str, list[EvidenceArtifact]] = {}
    for artifact in artifacts:
        if artifact.kind == "network-ndjson":
            network_artifacts_by_doc.setdefault(artifact.evidence_doc, []).append(artifact)

    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        if not _claim_requires_structured_network_evidence(claim):
            continue
        for config_path in claim.config_paths:
            if not _config_uses_network_emulation(root, config_path):
                continue
            retained_results = results_by_doc.get(claim.evidence_doc, {}).get(config_path, [])
            if not retained_results:
                continue

            has_evidence = False
            for result in retained_results:
                success_reason = result.get("success_reason", "")
                if not isinstance(success_reason, str):
                    success_reason = ""
                linked_path = _network_validation_artifact_path(success_reason)
                if linked_path:
                    linked_artifact = EvidenceArtifact(
                        evidence_doc=claim.evidence_doc,
                        evidence_path=root / claim.evidence_doc,
                        path=Path(linked_path),
                        kind="network-ndjson",
                        line=0,
                    )
                    if linked_artifact.path.is_file() and not _check_network_ndjson(
                        linked_artifact,
                    ):
                        has_evidence = True
                        break
                for artifact in network_artifacts_by_doc.get(claim.evidence_doc, []):
                    if _artifact_is_under_result_continuum_root(result, artifact.path):
                        has_evidence = True
                        break
                if has_evidence:
                    break

            if has_evidence:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "network-emulation-evidence-missing",
                    "%s %s config %s enables network emulation but retained evidence "
                    "does not link or reference a same-run network NDJSON artifact"
                    % (claim.evidence_doc, claim.row_id, config_path),
                )
            )
    return issues


def _claim_requires_structured_network_evidence(claim: EvidenceRowClaim) -> bool:
    row_text = claim.row_text.lower()
    return any(
        marker in row_text
        for marker in (
            "netperf",
            "network-validation",
            "network profile",
            "network outputs",
        )
    )


def _check_evidence_doc_profile_mentions(
    root: Path,
) -> list[EvidenceArtifactIssue]:
    """Ensure evidence docs name the profile IDs used by certified configs."""
    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        for config_path in claim.config_paths:
            for profile_id in _config_use_profiles_from_file(root, config_path):
                if _profile_id_mentioned(evidence_text, profile_id):
                    continue
                issues.append(
                    EvidenceArtifactIssue(
                        "evidence-doc-profile-id-missing",
                        "%s %s config %s uses profile %s but evidence does not mention it"
                        % (claim.evidence_doc, claim.row_id, config_path, profile_id),
                    )
                )
    return issues


def _profile_field_id(profile_field: str) -> str:
    """Return profile ID from either a profile path or a bare profile ID."""
    cleaned = profile_field.strip().strip("`").lower()
    if cleaned.endswith((".yaml", ".yml")):
        return Path(cleaned).stem
    return cleaned.rsplit("/", maxsplit=1)[-1]


def _check_evidence_doc_profile_fields(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure structured profile fields match certified config use profiles."""
    field_specs = (
        ("Provider profile", "environment"),
        ("Software profile", "software"),
    )
    configs_by_doc: dict[str, set[str]] = {}
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        configs_by_doc.setdefault(claim.evidence_doc, set()).update(claim.config_paths)

    issues = []
    test_results_by_doc = _test_result_artifacts_by_doc(artifacts)
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        fields = _evidence_table_fields(evidence_text)
        for evidence_field, config_field in field_specs:
            profile_field = fields.get(evidence_field, "")
            expected_profiles = {
                profile
                for config_path in claim.config_paths
                for profile in (
                    _config_use_profile_from_file(root, config_path, config_field),
                )
                if profile
            }
            if not expected_profiles:
                continue
            if not profile_field:
                if (
                    len(configs_by_doc.get(claim.evidence_doc, set())) == 1
                    and len(test_results_by_doc.get(claim.evidence_doc, [])) == 1
                    and len(expected_profiles) == 1
                    and _profile_id_mentioned(evidence_text, next(iter(expected_profiles)))
                ):
                    issues.append(
                        EvidenceArtifactIssue(
                            "evidence-doc-profile-field-missing",
                            "%s %s config %s uses %s profile %s but has no %s field"
                            % (
                                claim.evidence_doc,
                                claim.row_id,
                                claim.config_paths[0],
                                config_field,
                                next(iter(expected_profiles)),
                                evidence_field,
                            ),
                        )
                    )
                continue
            actual_profile = _profile_field_id(profile_field)
            if actual_profile in expected_profiles and len(expected_profiles) == 1:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-profile-field-mismatch",
                    "%s %s %s=%r but certified configs use %s profile(s): %s"
                    % (
                        claim.evidence_doc,
                        claim.row_id,
                        evidence_field,
                        profile_field,
                        config_field,
                        ", ".join(sorted(expected_profiles)),
                    ),
                )
            )
    return issues


def _artifact_continuum_root(path: Path) -> Optional[Path]:
    try:
        continuum_index = path.parts.index(".continuum")
    except ValueError:
        return None
    return Path(*path.parts[: continuum_index + 1])


def _test_result_artifacts_by_doc(
    artifacts: list[EvidenceArtifact],
) -> dict[str, list[EvidenceArtifact]]:
    test_results_by_doc: dict[str, list[EvidenceArtifact]] = {}
    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        test_results_by_doc.setdefault(artifact.evidence_doc, []).append(artifact)
    return test_results_by_doc


def _artifacts_by_doc(
    artifacts: list[EvidenceArtifact],
) -> dict[str, list[EvidenceArtifact]]:
    artifacts_by_doc: dict[str, list[EvidenceArtifact]] = {}
    for artifact in artifacts:
        artifacts_by_doc.setdefault(artifact.evidence_doc, []).append(artifact)
    return artifacts_by_doc


def _check_evidence_doc_artifact_root_fields(
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure Artifact root fields match retained test-results artifact roots."""
    issues = []
    for evidence_doc, test_results in sorted(_test_result_artifacts_by_doc(artifacts).items()):
        if len(test_results) != 1:
            continue
        artifact = test_results[0]
        fields = _evidence_table_fields(artifact.evidence_path.read_text(encoding="utf-8"))
        artifact_root = fields.get("Artifact root", "")
        if artifact_root:
            continue
        expected_root = _artifact_continuum_root(artifact.path)
        if expected_root is None:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-artifact-root-missing",
                "%s has one primary test-results artifact %s but no Artifact root field"
                % (evidence_doc, artifact.path),
            )
        )

    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        fields = _evidence_table_fields(artifact.evidence_path.read_text(encoding="utf-8"))
        artifact_root = fields.get("Artifact root", "")
        if not artifact_root:
            continue
        expected_root = _artifact_continuum_root(artifact.path)
        if expected_root is None:
            continue
        actual_root = Path(artifact_root.strip().strip("`"))
        try:
            roots_match = actual_root.resolve() == expected_root.resolve()
        except OSError:
            roots_match = actual_root == expected_root
        if roots_match:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-artifact-root-mismatch",
                "%s Artifact root=%r but %s is under %s"
                % (artifact.evidence_doc, artifact_root, artifact.path, expected_root),
            )
        )
    return issues


def _check_evidence_doc_result_summary_path_fields(
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure single-run evidence docs have a structured Result summary path."""
    issues = []
    for evidence_doc, test_results in sorted(_test_result_artifacts_by_doc(artifacts).items()):
        if len(test_results) != 1:
            continue
        artifact = test_results[0]
        fields = _evidence_table_fields(artifact.evidence_path.read_text(encoding="utf-8"))
        result_summary_path = fields.get("Result summary path", "")
        if not result_summary_path:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-result-summary-path-missing",
                    "%s has one primary test-results artifact %s but no "
                    "Result summary path field" % (evidence_doc, artifact.path),
                )
            )
            continue
        expected_path = artifact.path
        actual_path = Path(result_summary_path.strip().strip("`"))
        try:
            paths_match = actual_path.resolve() == expected_path.resolve()
        except OSError:
            paths_match = actual_path == expected_path
        if paths_match:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-result-summary-path-mismatch",
                "%s Result summary path=%r but primary test-results artifact is %s"
                % (evidence_doc, result_summary_path, expected_path),
            )
        )
    return issues


def _check_evidence_doc_required_artifact_fields(
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure evidence docs say which primary artifacts were checked."""
    issues = []
    for evidence_doc, doc_artifacts in sorted(_artifacts_by_doc(artifacts).items()):
        if not doc_artifacts:
            continue
        artifact = doc_artifacts[0]
        fields = _evidence_table_fields(artifact.evidence_path.read_text(encoding="utf-8"))
        required_artifacts = fields.get("Required artifacts checked", "")
        if not required_artifacts:
            test_results = [item for item in doc_artifacts if item.kind == "test-results"]
            detail = (
                "%s has one primary test-results artifact %s but no "
                "Required artifacts checked field" % (evidence_doc, test_results[0].path)
                if len(doc_artifacts) == 1 and len(test_results) == 1
                else "%s has %d primary evidence artifact(s) but no "
                "Required artifacts checked field" % (evidence_doc, len(doc_artifacts))
            )
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-required-artifacts-field-missing",
                    detail,
                )
            )
            continue
        missing_markers = _missing_required_artifact_field_markers(
            required_artifacts,
            fields.get("Runtime targets", ""),
            tuple(sorted({item.kind for item in doc_artifacts})),
        )
        if missing_markers:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-required-artifacts-field-incomplete",
                    "%s Required artifacts checked=%r is missing: %s"
                    % (evidence_doc, required_artifacts, ", ".join(missing_markers)),
                )
            )
        unexpected_markers = _unexpected_required_artifact_field_markers(
            required_artifacts,
            tuple(sorted({item.kind for item in doc_artifacts})),
        )
        if unexpected_markers:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-required-artifacts-field-overclaimed",
                    "%s Required artifacts checked=%r claims absent artifact kind(s): %s"
                    % (evidence_doc, required_artifacts, ", ".join(unexpected_markers)),
                )
            )
    return issues


def _missing_required_artifact_field_markers(
    required_artifacts: str,
    runtime_targets: str,
    artifact_kinds: tuple[str, ...],
) -> list[str]:
    """Return baseline artifact categories missing from an evidence field."""
    normalized = required_artifacts.lower().replace("`", "")
    missing = []
    if "test-results" in artifact_kinds:
        missing.extend(
            label
            for label, variants in REQUIRED_ARTIFACT_FIELD_MARKERS
            if not any(variant in normalized for variant in variants)
        )
    artifact_kind_set = set(artifact_kinds)
    for artifact_kind, marker_spec in REQUIRED_ARTIFACT_KIND_FIELD_MARKERS.items():
        if artifact_kind not in artifact_kind_set:
            continue
        label, variants = marker_spec
        if any(variant in normalized for variant in variants):
            continue
        missing.append(label)
    for runtime_target, label, variants in REQUIRED_RUNTIME_TARGET_FIELD_MARKERS:
        if not _runtime_target_mentioned(runtime_targets, runtime_target):
            continue
        if any(variant in normalized for variant in variants):
            continue
        missing.append(label)
    if _runtime_targets_claim_cleanup(runtime_targets) and not any(
        marker in normalized for marker in ("teardown", "cleanup")
    ):
        missing.append("teardown evidence")
    return missing


def _unexpected_required_artifact_field_markers(
    required_artifacts: str,
    artifact_kinds: tuple[str, ...],
) -> list[str]:
    """Return specialized artifact categories claimed but absent from evidence."""
    normalized = required_artifacts.lower().replace("`", "")
    artifact_kind_set = set(artifact_kinds)
    unexpected = []
    for artifact_kind, marker_spec in REQUIRED_ARTIFACT_KIND_FIELD_MARKERS.items():
        if artifact_kind in artifact_kind_set:
            continue
        label, variants = marker_spec
        if not any(variant in normalized for variant in variants):
            continue
        unexpected.append(label)
    return unexpected


def _check_evidence_doc_provider_prereqs_match_configs(
    root: Path,
) -> list[EvidenceArtifactIssue]:
    """Ensure local provider configs have explicit host-prerequisite evidence."""
    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        fields = _evidence_table_fields(evidence_path.read_text(encoding="utf-8"))
        prerequisites = fields.get("Provider / host prerequisites", "")
        if not prerequisites:
            continue
        prerequisites_lower = prerequisites.lower()
        for config_path in claim.config_paths:
            environment = _config_environment_from_file(root, config_path)
            if not environment.startswith("local-qemu"):
                continue
            missing = [
                marker
                for marker in ("qemu", "libvirt", "kvm", "no cloud credentials")
                if marker not in prerequisites_lower
            ]
            if not missing:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-local-qemu-prerequisites-missing",
                    "%s %s config %s uses environment %s but Provider / host "
                    "prerequisites is missing: %s"
                    % (
                        claim.evidence_doc,
                        claim.row_id,
                        config_path,
                        environment,
                        ", ".join(missing),
                    ),
                )
            )
    return issues


def _runtime_targets_claim_cleanup(runtime_targets: str) -> bool:
    lowered = runtime_targets.lower().replace("`", "")
    return "cleanup" in lowered or "teardown" in lowered


def _check_evidence_doc_cleanup_claims(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure cleanup/teardown runtime-scope claims have teardown evidence."""
    success_reasons_by_doc: dict[str, list[str]] = {}
    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        success_reasons_by_doc.setdefault(artifact.evidence_doc, []).extend(
            _artifact_success_reasons(artifact)
        )

    issues = []
    for evidence_doc in iter_evidence_docs(root):
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        fields = _evidence_table_fields(evidence_path.read_text(encoding="utf-8"))
        runtime_targets = fields.get("Runtime targets", "")
        if not _runtime_targets_claim_cleanup(runtime_targets):
            continue
        success_reasons = success_reasons_by_doc.get(evidence_doc, [])
        if any("teardown_verified" in success_reason for success_reason in success_reasons):
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-cleanup-claim-missing-teardown-evidence",
                "%s Runtime targets=%r claims cleanup/teardown but no retained "
                "test-results success_reason includes teardown_verified"
                % (evidence_doc, runtime_targets),
            )
        )
    return issues


def _check_result_state_phase(
    artifact: EvidenceArtifact,
    index: int,
    config_path: str,
    success_reason: str,
) -> list[EvidenceArtifactIssue]:
    repo_root = _repo_root_for_artifact(artifact)
    expected_phase, issue = _expected_state_phase_from_config(repo_root, config_path)
    if issue:
        return [issue]
    if expected_phase is None:
        return []

    match = STATE_PHASE_RE.search(success_reason)
    if not match:
        return []
    state_phase = match.group(1)
    if state_phase == expected_phase:
        return []
    return [
        EvidenceArtifactIssue(
            "test-results-entry-state-phase-mismatch",
            "%s results[%s] %s recorded state_phase=%s expected %s from run.targets"
            % (artifact.path, index, config_path, state_phase, expected_phase),
        )
    ]


def _success_reason_state_phase(success_reason: str) -> str:
    match = STATE_PHASE_RE.search(success_reason)
    return match.group(1) if match else ""


def _read_yaml_if_readable(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), None
    except PermissionError:
        return None, "unreadable"
    except (OSError, yaml.YAMLError) as exc:
        return None, str(exc)


def _read_json_if_readable(path: Path):
    try:
        return _load_json(path), None
    except PermissionError:
        return None, "unreadable"
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _check_lock_payload(
    artifact: EvidenceArtifact,
    index: int,
    lock_path: Path,
    payload,
    config_paths: tuple[str, ...],
) -> list[EvidenceArtifactIssue]:
    if not isinstance(payload, dict):
        return [
            EvidenceArtifactIssue(
                "test-results-entry-lock-invalid",
                "%s results[%s] experiment_lock.yaml is not a mapping" % (artifact.path, index),
            )
        ]

    issues = []
    if payload.get("kind") != "ContinuumExperimentLock":
        issues.append(
            EvidenceArtifactIssue(
                "test-results-entry-lock-kind-invalid",
                "%s results[%s] %s kind=%r"
                % (artifact.path, index, lock_path, payload.get("kind")),
            )
        )

    sources = payload.get("sources")
    experiment_source = sources.get("experiment") if isinstance(sources, dict) else None
    if config_paths:
        if not isinstance(experiment_source, str) or not any(
            experiment_source.endswith(config_path) for config_path in config_paths
        ):
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-lock-config-mismatch",
                    "%s results[%s] %s sources.experiment=%r expected one of: %s"
                    % (
                        artifact.path,
                        index,
                        lock_path,
                        experiment_source,
                        ", ".join(config_paths),
                    ),
                )
            )
    return issues


def _check_state_payload(
    artifact: EvidenceArtifact,
    index: int,
    state_path: Path,
    payload,
    success_reason: str,
) -> list[EvidenceArtifactIssue]:
    if not isinstance(payload, dict):
        return [
            EvidenceArtifactIssue(
                "test-results-entry-state-invalid",
                "%s results[%s] state.json is not a mapping" % (artifact.path, index),
            )
        ]

    expected_phase = _success_reason_state_phase(success_reason)
    if not expected_phase or payload.get("phase_completed") == expected_phase:
        return []
    return [
        EvidenceArtifactIssue(
            "test-results-entry-state-file-phase-mismatch",
            "%s results[%s] %s phase_completed=%r expected %s from success_reason"
            % (artifact.path, index, state_path, payload.get("phase_completed"), expected_phase),
        )
    ]


def _check_resume_contract_payloads(
    artifact: EvidenceArtifact,
    index: int,
    lock_payload,
    state_payload,
) -> list[EvidenceArtifactIssue]:
    if not isinstance(lock_payload, dict) or not isinstance(state_payload, dict):
        return []
    lock_contract = lock_payload.get("resume_contract")
    state_contract = state_payload.get("resume_contract")
    if not isinstance(lock_contract, dict) or not isinstance(state_contract, dict):
        return []
    if lock_contract.get("hash") == state_contract.get("hash"):
        return []
    return [
        EvidenceArtifactIssue(
            "test-results-entry-resume-contract-mismatch",
            "%s results[%s] experiment_lock.yaml resume_contract hash %r does not "
            "match state.json hash %r"
            % (
                artifact.path,
                index,
                lock_contract.get("hash"),
                state_contract.get("hash"),
            ),
        )
    ]


def _check_result_persistence_artifacts(
    artifact: EvidenceArtifact,
    index: int,
    result: dict,
    success_reason: str,
    result_config_paths: tuple[str, ...],
) -> list[EvidenceArtifactIssue]:
    issues = []
    continuum_root = _continuum_root_from_result(result)
    if continuum_root is None:
        return [
            EvidenceArtifactIssue(
                "test-results-entry-continuum-root-missing",
                "%s results[%s] cannot derive .continuum root from artifacts"
                % (artifact.path, index),
            )
        ]

    lock_payload = None
    state_payload = None
    lock_path = continuum_root / "experiment_lock.yaml"
    if "experiment_lock_written" in success_reason:
        if not lock_path.is_file():
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-lock-missing",
                    "%s results[%s] success_reason claims experiment_lock_written "
                    "but %s is missing" % (artifact.path, index, lock_path),
                )
            )
        else:
            lock_payload, error = _read_yaml_if_readable(lock_path)
            if error and error != "unreadable":
                issues.append(
                    EvidenceArtifactIssue(
                        "test-results-entry-lock-yaml-invalid",
                        "%s results[%s] %s: %s" % (artifact.path, index, lock_path, error),
                    )
                )
            elif error is None:
                issues.extend(
                    _check_lock_payload(
                        artifact,
                        index,
                        lock_path,
                        lock_payload,
                        result_config_paths,
                    )
                )

    state_path = continuum_root / "state.json"
    if "state_file_written" in success_reason:
        if not state_path.is_file():
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-state-missing",
                    "%s results[%s] success_reason claims state_file_written "
                    "but %s is missing" % (artifact.path, index, state_path),
                )
            )
        else:
            state_payload, error = _read_json_if_readable(state_path)
            if error and error != "unreadable":
                issues.append(
                    EvidenceArtifactIssue(
                        "test-results-entry-state-json-invalid",
                        "%s results[%s] %s: %s" % (artifact.path, index, state_path, error),
                    )
                )
            elif error is None:
                issues.extend(
                    _check_state_payload(
                        artifact,
                        index,
                        state_path,
                        state_payload,
                        success_reason,
                    )
                )

    if "resume_contract_match" in success_reason:
        issues.extend(
            _check_resume_contract_payloads(
                artifact,
                index,
                lock_payload,
                state_payload,
            )
        )
    return issues


def _check_test_results(artifact: EvidenceArtifact) -> list[EvidenceArtifactIssue]:
    issues = []
    try:
        payload = _load_json(artifact.path)
    except (OSError, json.JSONDecodeError) as exc:
        return [
            EvidenceArtifactIssue(
                "artifact-json-invalid",
                "%s: %s" % (artifact.path, exc),
            )
        ]

    artifacts_dir_path = None
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        issues.append(
            EvidenceArtifactIssue(
                "test-results-timestamp-missing",
                "%s has no timestamp" % (artifact.path,),
            )
        )
    else:
        expected_timestamp = _test_results_filename_timestamp(artifact.path)
        if expected_timestamp and timestamp != expected_timestamp:
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-timestamp-mismatch",
                    "%s timestamp=%r expected %r from filename"
                    % (artifact.path, timestamp, expected_timestamp),
                )
            )

    artifacts_dir = payload.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir.strip():
        issues.append(
            EvidenceArtifactIssue(
                "test-results-artifacts-dir-missing",
                "%s has no artifacts_dir" % (artifact.path,),
            )
        )
    else:
        candidate_artifacts_dir = Path(artifacts_dir)
        if not candidate_artifacts_dir.is_dir():
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-artifacts-dir-missing",
                    "%s references missing artifacts_dir %s" % (artifact.path, artifacts_dir),
                )
            )
        else:
            artifacts_dir_path = candidate_artifacts_dir
            expected_artifacts_dir = artifact.path.with_suffix("")
            if candidate_artifacts_dir.resolve() != expected_artifacts_dir.resolve():
                issues.append(
                    EvidenceArtifactIssue(
                        "test-results-artifacts-dir-mismatch",
                        "%s artifacts_dir=%s expected %s"
                        % (artifact.path, artifacts_dir, expected_artifacts_dir),
                    )
                )

    total = payload.get("total_tests")
    passed = payload.get("passed")
    failed = payload.get("failed")
    if not isinstance(total, int) or total < 1:
        issues.append(
            EvidenceArtifactIssue(
                "test-results-invalid-total",
                "%s total_tests=%r" % (artifact.path, total),
            )
        )
    if not isinstance(passed, int) or passed < 1:
        issues.append(
            EvidenceArtifactIssue(
                "test-results-invalid-passed",
                "%s passed=%r" % (artifact.path, passed),
            )
        )
    if failed != 0:
        issues.append(
            EvidenceArtifactIssue("test-results-failed", "%s failed=%r" % (artifact.path, failed))
        )
    if isinstance(total, int) and isinstance(passed, int) and isinstance(failed, int):
        if total != passed + failed:
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-count-mismatch",
                    "%s total=%s passed=%s failed=%s" % (artifact.path, total, passed, failed),
                )
            )

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        issues.append(EvidenceArtifactIssue("test-results-missing-results", str(artifact.path)))
        return issues
    result_config_paths = tuple(
        sorted(
            {
                result.get("config_path")
                for result in results
                if isinstance(result, dict)
                and isinstance(result.get("config_path"), str)
                and result.get("config_path")
            }
        )
    )
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-invalid",
                    "%s results[%s] is not a mapping" % (artifact.path, index),
                )
            )
            continue
        if result.get("success") is not True:
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-failed",
                    "%s results[%s] success=%r" % (artifact.path, index, result.get("success")),
                )
            )
        if result.get("exit_code") != 0:
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-exit-code",
                    "%s results[%s] exit_code=%r" % (artifact.path, index, result.get("exit_code")),
                )
            )
        config_path = result.get("config_path")
        if not isinstance(config_path, str) or not config_path.strip():
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-config-path-missing",
                    "%s results[%s] has no config_path" % (artifact.path, index),
                )
            )
        start_time = result.get("start_time")
        if not isinstance(start_time, str) or not start_time.strip():
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-start-time-missing",
                    "%s results[%s] has no start_time" % (artifact.path, index),
                )
            )
        execution_time = result.get("execution_time")
        if not isinstance(execution_time, (int, float)) or execution_time < 0:
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-execution-time-invalid",
                    "%s results[%s] execution_time=%r"
                    % (artifact.path, index, execution_time),
                )
            )
        if result.get("timed_out") is not False:
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-timed-out",
                    "%s results[%s] timed_out=%r" % (artifact.path, index, result.get("timed_out")),
                )
            )
        base_images_rebuilt = result.get("base_images_rebuilt")
        if not isinstance(base_images_rebuilt, list):
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-base-images-invalid",
                    "%s results[%s] base_images_rebuilt=%r"
                    % (artifact.path, index, base_images_rebuilt),
                )
            )
        parameter_overrides = result.get("parameter_overrides")
        if not isinstance(parameter_overrides, dict):
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-parameter-overrides-invalid",
                    "%s results[%s] parameter_overrides=%r"
                    % (artifact.path, index, parameter_overrides),
                )
            )
        for artifact_field in REQUIRED_TEST_RESULT_ARTIFACT_FIELDS:
            artifact_value = result.get(artifact_field)
            if not isinstance(artifact_value, str) or not artifact_value.strip():
                issues.append(
                    EvidenceArtifactIssue(
                        "test-results-entry-artifact-field-missing",
                        "%s results[%s] has no %s" % (artifact.path, index, artifact_field),
                    )
                )
                continue
            artifact_path = Path(artifact_value)
            if artifacts_dir_path is not None and not _path_is_under(
                artifact_path,
                artifacts_dir_path,
            ):
                issues.append(
                    EvidenceArtifactIssue(
                        "test-results-entry-artifact-outside-artifacts-dir",
                        "%s results[%s] %s=%s is outside artifacts_dir %s"
                        % (
                            artifact.path,
                            index,
                            artifact_field,
                            artifact_value,
                            artifacts_dir_path,
                        ),
                    )
                )
            if artifact_path.is_file():
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-artifact-missing",
                    "%s results[%s] %s references missing %s"
                    % (artifact.path, index, artifact_field, artifact_value),
                )
            )
        issues.extend(_check_test_result_metadata(artifact, index, result))
        success_reason = result.get("success_reason")
        if not isinstance(success_reason, str) or not success_reason.strip():
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-missing-success-reason",
                    "%s results[%s] has no success_reason" % (artifact.path, index),
                )
            )
            continue
        for token in REQUIRED_SUCCESS_REASON_TOKENS:
            if token in success_reason:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "test-results-entry-success-reason-missing-token",
                    "%s results[%s] success_reason missing %s" % (artifact.path, index, token),
                )
            )
        if isinstance(config_path, str) and config_path.strip():
            issues.extend(
                _check_result_state_phase(
                    artifact,
                    index,
                    config_path,
                    success_reason,
                )
            )
        issues.extend(
            _check_result_persistence_artifacts(
                artifact,
                index,
                result,
                success_reason,
                result_config_paths,
            )
        )
    return issues


def _check_test_result_metadata(
    artifact: EvidenceArtifact,
    index: int,
    result: dict,
) -> list[EvidenceArtifactIssue]:
    """Validate per-result metadata artifact consistency with the summary entry."""
    metadata_artifact = result.get("metadata_artifact")
    if not isinstance(metadata_artifact, str) or not metadata_artifact.strip():
        return []
    metadata_path = Path(metadata_artifact)
    if not metadata_path.is_file():
        return []
    try:
        metadata = _load_json(metadata_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [
            EvidenceArtifactIssue(
                "test-results-entry-metadata-json-invalid",
                "%s results[%s] metadata_artifact=%s: %s"
                % (artifact.path, index, metadata_artifact, exc),
            )
        ]

    if not isinstance(metadata, dict):
        return [
            EvidenceArtifactIssue(
                "test-results-entry-metadata-invalid",
                "%s results[%s] metadata_artifact=%s is not a mapping"
                % (artifact.path, index, metadata_artifact),
            )
        ]

    issues = []
    for field in REQUIRED_TEST_RESULT_METADATA_FIELDS:
        if metadata.get(field) == result.get(field):
            continue
        issues.append(
            EvidenceArtifactIssue(
                "test-results-entry-metadata-mismatch",
                "%s results[%s] metadata %s=%r expected %r"
                % (artifact.path, index, field, metadata.get(field), result.get(field)),
            )
        )
    return issues


def _check_cloud_static_audit(artifact: EvidenceArtifact) -> list[EvidenceArtifactIssue]:
    try:
        text = artifact.path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            EvidenceArtifactIssue(
                "artifact-read-failed",
                "%s: %s" % (artifact.path, exc),
            )
        ]

    required_section = _required_gate_lines(text)

    if not required_section:
        return [EvidenceArtifactIssue("cloud-audit-missing-required-gates", str(artifact.path))]

    issues = []
    present_gates = {_required_gate_name(line) for line in required_section}
    for gate in REQUIRED_CLOUD_AUDIT_GATES:
        if gate in present_gates:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "cloud-audit-required-gate-missing",
                "%s missing required gate %s" % (artifact.path, gate),
            )
        )
    for line in required_section:
        if not line.endswith(": PASS"):
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-required-gate-failed",
                    "%s: %s" % (artifact.path, line),
                )
            )
    issues.extend(_check_cloud_audit_release_readiness(artifact, text))
    issues.extend(_check_cloud_audit_evidence_summary(artifact, text))
    return issues


def check_cloud_static_audit_report(
    report_path: Path,
    evidence_doc: str,
    evidence_path: Path,
) -> list[EvidenceArtifactIssue]:
    """Validate one cloud-static audit report referenced by release evidence."""
    return _check_cloud_static_audit(
        EvidenceArtifact(
            evidence_doc=evidence_doc,
            evidence_path=evidence_path,
            path=report_path,
            kind="cloud-static-audit",
            line=0,
        )
    )


def _required_gate_lines(text: str) -> list[str]:
    required_section = []
    in_required = False
    for line in text.splitlines():
        if line.startswith("## Required Gates"):
            in_required = True
            continue
        if in_required and line.startswith("## "):
            break
        if in_required and line.startswith("- "):
            required_section.append(line)
    return required_section


def _required_gate_name(line: str) -> str:
    gate_text = line[2:] if line.startswith("- ") else line
    return gate_text.split(":", 1)[0].strip()


def _informational_check_statuses(text: str) -> dict[str, str]:
    statuses = {}
    in_informational = False
    for line in text.splitlines():
        if line.startswith("## Informational Checks"):
            in_informational = True
            continue
        if in_informational and line.startswith("## "):
            break
        if not in_informational or not line.startswith("- "):
            continue
        check_text = line[2:]
        if ":" not in check_text:
            continue
        name, status = check_text.split(":", 1)
        statuses[name.strip()] = status.strip()
    return statuses


def _check_cloud_audit_release_readiness(
    artifact: EvidenceArtifact,
    report_text: str,
) -> list[EvidenceArtifactIssue]:
    """Validate release-readiness entries in the cloud-safe audit report."""
    issues = []
    statuses = _informational_check_statuses(report_text)

    for check_name, allowed_statuses in REQUIRED_CLOUD_AUDIT_INFORMATIONAL_CHECKS.items():
        status = statuses.get(check_name)
        if not status:
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-informational-check-missing",
                    "%s missing informational check %s" % (artifact.path, check_name),
                )
            )
            continue
        if any(
            status == allowed or status.startswith(allowed + " ")
            for allowed in allowed_statuses
        ):
            continue
        issues.append(
            EvidenceArtifactIssue(
                "cloud-audit-informational-check-status",
                "%s %s=%r expected one of %s"
                % (artifact.path, check_name, status, ", ".join(allowed_statuses)),
            )
        )

    for heading, total_re, total_name in REQUIRED_CLOUD_AUDIT_ZERO_TOTALS:
        total = _extract_release_total(report_text, heading, total_re)
        if total is None:
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-zero-total-missing",
                    "%s missing %s output" % (artifact.path, total_name),
                )
            )
            continue
        if total == 0:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "cloud-audit-zero-total-nonzero",
                "%s %s=%d expected 0" % (artifact.path, total_name, total),
            )
        )

    artifact_audit_total = _extract_release_total(
        report_text,
        "### release evidence artifact audit",
        ARTIFACT_AUDIT_TOTAL_RE,
    )
    if artifact_audit_total is None:
        issues.append(
            EvidenceArtifactIssue(
                "cloud-audit-artifact-audit-total-missing",
                "%s missing TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES output"
                % (artifact.path,),
            )
        )
    elif artifact_audit_total != 0:
        issues.append(
            EvidenceArtifactIssue(
                "cloud-audit-artifact-audit-total-nonzero",
                "%s TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=%d expected 0"
                % (artifact.path, artifact_audit_total),
            )
        )

    pretag_total = _extract_release_total(
        report_text,
        "### M1 pre-tag readiness check",
        PRETAG_TOTAL_RE,
    )
    if pretag_total is None:
        issues.append(
            EvidenceArtifactIssue(
                "cloud-audit-pretag-total-missing",
                "%s missing TOTAL_RELEASE_PRETAG_ISSUES output" % (artifact.path,),
            )
        )
    else:
        pretag_status = statuses.get("M1 pre-tag readiness check", "")
        if (pretag_status == "OK" or pretag_status.startswith("OK ")) and pretag_total != 0:
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-pretag-status-total-mismatch",
                    "%s M1 pre-tag readiness check=%r but TOTAL_RELEASE_PRETAG_ISSUES=%d"
                    % (artifact.path, pretag_status, pretag_total),
                )
            )
        if pretag_status.startswith("FINDINGS OR UNAVAILABLE") and pretag_total == 0:
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-pretag-status-total-mismatch",
                    "%s M1 pre-tag readiness check=%r but TOTAL_RELEASE_PRETAG_ISSUES=0"
                    % (artifact.path, pretag_status),
                )
            )
    return issues


def _extract_release_total(
    report_text: str,
    heading: str,
    total_re: re.Pattern[str],
) -> Optional[int]:
    section = _section_text(report_text, heading)
    match = total_re.search(section)
    if not match:
        return None
    return int(match.group(1))


def _required_gates_pass_text(report_text: str) -> Optional[str]:
    required_section = _required_gate_lines(report_text)
    if not required_section:
        return None
    present_gates = {_required_gate_name(line) for line in required_section}
    if any(gate not in present_gates for gate in REQUIRED_CLOUD_AUDIT_GATES):
        return None
    if not all(line.endswith(": PASS") for line in required_section):
        return None
    return "PASS"


def _section_text(text: str, heading: str) -> str:
    collecting = False
    lines = []
    for line in text.splitlines():
        if line.startswith("### "):
            if collecting:
                return "\n".join(lines).strip()
            collecting = line.strip() == heading
            continue
        if collecting:
            lines.append(line)
    return "\n".join(lines).strip()


def _extract_unittest_count(text: str, heading: str) -> Optional[int]:
    match = UNITTEST_COUNT_RE.search(_section_text(text, heading))
    return int(match.group(1)) if match else None


def _extract_pytest_count(text: str, heading: str) -> Optional[int]:
    match = PYTEST_COUNT_RE.search(_section_text(text, heading))
    return int(match.group(1)) if match else None


def _evidence_table_fields(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = _markdown_cells(line)
        if len(cells) < 2:
            continue
        if cells[0] in ("Field", "---"):
            continue
        if cells[0] in fields:
            continue
        fields[cells[0]] = _normalize_field_value(cells[1])
    return fields


def _evidence_section_table_fields(text: str, marker: str) -> dict[str, str]:
    """Return fields from the first markdown table after a marker line."""
    fields = {}
    marker_seen = False
    table_seen = False
    marker_lower = marker.lower()
    for line in text.splitlines():
        if not marker_seen:
            marker_seen = line.strip().lower().startswith(marker_lower)
            continue
        if not line.strip():
            if table_seen:
                break
            continue
        if not line.startswith("| "):
            if table_seen:
                break
            continue
        table_seen = True
        cells = _markdown_cells(line)
        if len(cells) < 2:
            continue
        if cells[0] in ("Field", "---"):
            continue
        if cells[0] in fields:
            continue
        fields[cells[0]] = _normalize_field_value(cells[1])
    return fields


def _field_expectation_issues(
    artifact: EvidenceArtifact,
    fields: dict[str, str],
    expectations: dict[str, Optional[str]],
) -> list[EvidenceArtifactIssue]:
    issues = []
    for field, expected in expectations.items():
        if field not in fields:
            continue
        if expected is None:
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-report-count-missing",
                    "%s could not derive %s from %s"
                    % (artifact.evidence_doc, field, artifact.path),
                )
            )
            continue
        if fields[field] != expected:
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-evidence-summary-mismatch",
                    "%s %s=%r expected %r from %s"
                    % (artifact.evidence_doc, field, fields[field], expected, artifact.path),
                )
            )
    return issues


def _check_cloud_audit_evidence_summary(
    artifact: EvidenceArtifact,
    report_text: str,
) -> list[EvidenceArtifactIssue]:
    try:
        evidence_text = artifact.evidence_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            EvidenceArtifactIssue(
                "evidence-doc-read-failed",
                "%s: %s" % (artifact.evidence_doc, exc),
            )
        ]

    fields = _evidence_table_fields(evidence_text)
    expectations = {
        "Required gates": _required_gates_pass_text(report_text),
        "Unit unittest discovery": _count_text(
            _extract_unittest_count(report_text, "### unit unittest discovery"),
            "tests OK",
        ),
        "E2E unittest discovery": _count_text(
            _extract_unittest_count(report_text, "### e2e unittest discovery"),
            "tests OK",
        ),
        "Combined unittest discovery": _count_text(
            _extract_unittest_count(report_text, "### combined unittest discovery"),
            "tests OK",
        ),
        "Pytest mirror": _count_text(
            _extract_pytest_count(report_text, "### combined pytest suite"),
            "passed",
        ),
    }
    if "Marker debt scan" in fields:
        marker_clean_line = "- " + "TO" + "DO/" + "FIX" + "ME debt scan: NO MATCHES"
        expectations["Marker debt scan"] = (
            "NO MATCHES" if marker_clean_line in report_text else None
        )
    return _field_expectation_issues(artifact, fields, expectations)


def _count_text(count: Optional[int], suffix: str) -> Optional[str]:
    if count is None:
        return None
    return "%s %s" % (count, suffix)


def _check_benchmark_manifest(artifact: EvidenceArtifact) -> list[EvidenceArtifactIssue]:
    issues = []
    try:
        payload = _load_json(artifact.path)
    except (OSError, json.JSONDecodeError) as exc:
        return [
            EvidenceArtifactIssue(
                "artifact-json-invalid",
                "%s: %s" % (artifact.path, exc),
            )
        ]

    if payload.get("kind") != "ContinuumBenchmarkMetrics":
        issues.append(
            EvidenceArtifactIssue(
                "benchmark-manifest-kind-invalid",
                "%s kind=%r" % (artifact.path, payload.get("kind")),
            )
        )

    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        issues.append(
            EvidenceArtifactIssue("benchmark-manifest-missing-tables", str(artifact.path))
        )
        return issues

    for index, table in enumerate(tables):
        if not isinstance(table, dict):
            issues.append(
                EvidenceArtifactIssue(
                    "benchmark-manifest-table-invalid",
                    "%s tables[%s] is not a mapping" % (artifact.path, index),
                )
            )
            continue
        rows = table.get("rows")
        if not isinstance(rows, int) or rows < 1:
            issues.append(
                EvidenceArtifactIssue(
                    "benchmark-manifest-table-empty",
                    "%s tables[%s] rows=%r" % (artifact.path, index, rows),
                )
            )
        table_path = table.get("path")
        if isinstance(table_path, str) and table_path:
            if not Path(table_path).is_file():
                issues.append(
                    EvidenceArtifactIssue(
                        "benchmark-manifest-table-missing",
                        "%s references missing table %s" % (artifact.path, table_path),
                    )
                )
        else:
            issues.append(
                EvidenceArtifactIssue(
                    "benchmark-manifest-table-path-missing",
                    "%s tables[%s] has no path" % (artifact.path, index),
                )
            )
    return issues


def _check_network_ndjson(artifact: EvidenceArtifact) -> list[EvidenceArtifactIssue]:
    issues = []
    try:
        lines = artifact.path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [
            EvidenceArtifactIssue(
                "artifact-read-failed",
                "%s: %s" % (artifact.path, exc),
            )
        ]

    payload_lines = [line for line in lines if line.strip()]
    if not payload_lines:
        return [EvidenceArtifactIssue("network-ndjson-empty", str(artifact.path))]

    for index, line in enumerate(payload_lines, 1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(
                EvidenceArtifactIssue(
                    "network-ndjson-json-invalid",
                    "%s line %s: %s" % (artifact.path, index, exc),
                )
            )
            continue
        for key in ("source", "target", "direction", "output"):
            if key not in payload:
                issues.append(
                    EvidenceArtifactIssue(
                        "network-ndjson-key-missing",
                        "%s line %s missing %s" % (artifact.path, index, key),
                    )
                )
    return issues


def check_artifact(artifact: EvidenceArtifact) -> list[EvidenceArtifactIssue]:
    """Validate one local evidence artifact."""
    if not artifact.path.exists():
        return [
            EvidenceArtifactIssue(
                "artifact-missing",
                "%s:%s references missing %s"
                % (artifact.evidence_doc, artifact.line, artifact.path),
            )
        ]
    if not artifact.path.is_file():
        return [
            EvidenceArtifactIssue(
                "artifact-not-file",
                "%s:%s references non-file %s"
                % (artifact.evidence_doc, artifact.line, artifact.path),
            )
        ]

    handlers = {
        "test-results": _check_test_results,
        "cloud-static-audit": _check_cloud_static_audit,
        "benchmark-metrics-manifest": _check_benchmark_manifest,
        "network-ndjson": _check_network_ndjson,
    }
    handler = handlers.get(artifact.kind)
    if handler is None:
        return [
            EvidenceArtifactIssue(
                "artifact-kind-unknown",
                "%s kind=%s" % (artifact.path, artifact.kind),
            )
        ]
    return handler(artifact)


def _artifact_result_configs(artifact: EvidenceArtifact) -> set[str]:
    try:
        payload = _load_json(artifact.path)
    except (OSError, json.JSONDecodeError):
        return set()

    configs = set()
    results = payload.get("results")
    if not isinstance(results, list):
        return configs
    for result in results:
        if not isinstance(result, dict):
            continue
        config_path = result.get("config_path")
        if isinstance(config_path, str) and config_path:
            configs.add(config_path)
    return configs


def _artifact_success_reasons(artifact: EvidenceArtifact) -> list[str]:
    try:
        payload = _load_json(artifact.path)
    except (OSError, json.JSONDecodeError):
        return []

    reasons = []
    results = payload.get("results")
    if not isinstance(results, list):
        return reasons
    for result in results:
        if not isinstance(result, dict):
            continue
        success_reason = result.get("success_reason")
        if isinstance(success_reason, str) and success_reason:
            reasons.append(success_reason)
    return reasons


def _artifact_stdout_paths(artifact: EvidenceArtifact) -> list[Path]:
    try:
        payload = _load_json(artifact.path)
    except (OSError, json.JSONDecodeError):
        return []

    paths = []
    results = payload.get("results")
    if not isinstance(results, list):
        return paths
    for result in results:
        if not isinstance(result, dict):
            continue
        stdout_artifact = result.get("stdout_artifact")
        if isinstance(stdout_artifact, str) and stdout_artifact.strip():
            paths.append(Path(stdout_artifact))
    return paths


def _stdout_texts_by_doc(artifacts: list[EvidenceArtifact]) -> dict[str, list[str]]:
    stdout_texts: dict[str, list[str]] = {}
    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        for stdout_path in _artifact_stdout_paths(artifact):
            try:
                stdout_text = stdout_path.read_text(encoding="utf-8")
            except OSError:
                continue
            stdout_texts.setdefault(artifact.evidence_doc, []).append(stdout_text)
    return stdout_texts


def _check_claimed_stdout_markers(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure evidence-doc stdout claims are backed by retained stdout markers."""
    stdout_texts_by_doc = _stdout_texts_by_doc(artifacts)
    issues = []

    for evidence_doc in iter_evidence_docs(root):
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        for claim_id, claim_re, required_markers in CLAIMED_STDOUT_MARKERS:
            if not claim_re.search(evidence_text):
                continue
            stdout_texts = stdout_texts_by_doc.get(evidence_doc, [])
            if any(
                all(marker in stdout_text for marker in required_markers)
                for stdout_text in stdout_texts
            ):
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-stdout-marker-missing",
                    "%s claims %s but retained stdout artifacts do not contain: %s"
                    % (evidence_doc, claim_id, ", ".join(required_markers)),
                )
            )
    return issues


def _check_specialized_artifact_links(
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure specialized artifacts are named by retained successful-run metadata."""
    success_reasons_by_doc: dict[str, list[str]] = {}
    results_by_doc: dict[str, list[dict]] = {}
    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        success_reasons_by_doc.setdefault(artifact.evidence_doc, []).extend(
            _artifact_success_reasons(artifact)
        )
        for result_configs in _artifact_results_by_config([artifact]).values():
            for results in result_configs.values():
                results_by_doc.setdefault(artifact.evidence_doc, []).extend(results)

    issues = []
    for artifact in artifacts:
        if artifact.kind not in ("benchmark-metrics-manifest", "network-ndjson"):
            continue
        success_reasons = success_reasons_by_doc.get(artifact.evidence_doc, [])
        if any(artifact.path.as_posix() in success_reason for success_reason in success_reasons):
            continue
        if artifact.kind == "network-ndjson":
            if any(
                _artifact_is_under_result_continuum_root(result, artifact.path)
                for result in results_by_doc.get(artifact.evidence_doc, [])
            ):
                continue
        issues.append(
            EvidenceArtifactIssue(
                "specialized-artifact-not-linked-from-test-results",
                "%s references %s but no retained test-results success_reason names it"
                % (artifact.evidence_doc, artifact.path),
            )
        )
    return issues


def _check_evidence_docs_have_primary_artifacts(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure each referenced evidence document names at least one primary artifact."""
    artifact_docs = {artifact.evidence_doc for artifact in artifacts}
    issues = []
    for evidence_doc in iter_evidence_docs(root):
        if not (root / evidence_doc).exists():
            continue
        if evidence_doc in artifact_docs:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-primary-artifact-missing",
                "%s names no primary artifact path" % (evidence_doc,),
            )
        )
    return issues


def _check_cloud_audit_ready_suite_prereqs(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure the cloud-static audit checked prerequisites for ready-row suites."""
    suite_names = sorted(
        {
            suite_name
            for claim in iter_ready_row_claims(root)
            for suite_name in claim.suite_names
        }
    )
    if not suite_names:
        return []

    issues = []
    for artifact in artifacts:
        if artifact.kind != "cloud-static-audit":
            continue
        try:
            report_text = artifact.path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(
                EvidenceArtifactIssue(
                    "artifact-read-failed",
                    "%s: %s" % (artifact.path, exc),
                )
            )
            continue
        prereq_suites = set(SUITE_PREREQ_RE.findall(report_text))
        prereq_statuses = _informational_check_statuses(report_text)
        for suite_name in suite_names:
            if suite_name not in prereq_suites:
                issues.append(
                    EvidenceArtifactIssue(
                        "cloud-audit-ready-suite-prereq-missing",
                        "%s missing --check-prereqs coverage for ready suite %s"
                        % (artifact.path, suite_name),
                    )
                )
                continue

            status_title = CLOUD_AUDIT_PREREQ_STATUS_TITLE_BY_SUITE.get(suite_name)
            if status_title is None:
                issues.append(
                    EvidenceArtifactIssue(
                        "cloud-audit-ready-suite-prereq-status-unknown",
                        "%s has no cloud-audit prereq status title for ready suite %s"
                        % (artifact.path, suite_name),
                    )
                )
                continue
            status = prereq_statuses.get(status_title)
            if not status:
                issues.append(
                    EvidenceArtifactIssue(
                        "cloud-audit-ready-suite-prereq-status-missing",
                        "%s missing informational status %s for ready suite %s"
                        % (artifact.path, status_title, suite_name),
                    )
                )
                continue
            if status == "OK" or status.startswith("OK "):
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-ready-suite-prereq-status-not-ok",
                    "%s ready suite %s prereq status %s=%r expected OK"
                    % (artifact.path, suite_name, status_title, status),
                )
            )
    return issues


def _parity_suite_names(root: Path) -> list[str]:
    test_config_path = root / TEST_CONFIG_PATH
    if not test_config_path.exists():
        return []
    try:
        test_config = _load_json(test_config_path)
    except (OSError, json.JSONDecodeError):
        return []

    suites = test_config.get("test_suites")
    if not isinstance(suites, dict):
        return []

    parity_suites = []
    for suite_name, suite_config in suites.items():
        if not isinstance(suite_name, str) or not isinstance(suite_config, dict):
            continue
        directories = suite_config.get("directories")
        if not isinstance(directories, list):
            continue
        if any(
            isinstance(directory, str)
            and directory.startswith("configs/experiments/parity/")
            for directory in directories
        ):
            parity_suites.append(suite_name)
    return sorted(parity_suites)


def _check_cloud_audit_all_parity_suite_prereqs(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure cloud-static audit artifacts expose every configured parity suite prereq."""
    suite_names = _parity_suite_names(root)
    if not suite_names:
        return []

    issues = []
    for artifact in artifacts:
        if artifact.kind != "cloud-static-audit":
            continue
        try:
            report_text = artifact.path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(
                EvidenceArtifactIssue(
                    "artifact-read-failed",
                    "%s: %s" % (artifact.path, exc),
                )
            )
            continue
        prereq_suites = set(SUITE_PREREQ_RE.findall(report_text))
        for suite_name in suite_names:
            if suite_name in prereq_suites:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "cloud-audit-parity-suite-prereq-missing",
                    "%s missing --check-prereqs coverage for parity suite %s"
                    % (artifact.path, suite_name),
                )
            )
    return issues


def _check_cloud_audit_latest_report(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure release evidence points at the newest generated cloud audit report."""
    report_dir = (root / "logs" / "cloud_static_audit").resolve()
    if not report_dir.is_dir():
        return []

    reports = sorted(report_dir.glob("cloud_static_audit_*.md"), key=lambda path: path.name)
    if not reports:
        return []
    latest_report = reports[-1].resolve()

    issues = []
    for artifact in artifacts:
        if artifact.kind != "cloud-static-audit":
            continue
        artifact_path = artifact.path.resolve()
        if artifact_path.parent != report_dir:
            continue
        if artifact_path == latest_report:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "cloud-audit-report-not-latest",
                "%s references %s but latest cloud audit report is %s"
                % (artifact.evidence_doc, artifact.path, latest_report),
            )
        )
    return issues


def _check_claimed_config_results(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure certified row configs appear in the retained runner summaries."""
    claims = iter_ready_row_claims(root)
    result_configs_by_doc: dict[str, set[str]] = {}
    test_results_by_doc: dict[str, list[EvidenceArtifact]] = {}

    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        result_configs_by_doc.setdefault(artifact.evidence_doc, set()).update(
            _artifact_result_configs(artifact)
        )
        test_results_by_doc.setdefault(artifact.evidence_doc, []).append(artifact)

    issues = []
    for claim in claims:
        if not claim.config_paths:
            continue
        if claim.evidence_doc not in test_results_by_doc:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-missing-test-results",
                    "%s %s has no retained test-results artifact"
                    % (claim.evidence_doc, claim.row_id),
                )
            )
            continue
        result_configs = result_configs_by_doc.get(claim.evidence_doc, set())
        for config_path in claim.config_paths:
            if config_path in result_configs:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-config-not-run",
                    "%s %s expected %s in retained test-results"
                    % (claim.evidence_doc, claim.row_id, config_path),
                )
            )
    return issues


def _check_evidence_doc_config_mentions(root: Path) -> list[EvidenceArtifactIssue]:
    """Ensure release evidence docs explicitly name certified experiment configs."""
    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        for config_path in claim.config_paths:
            if config_path in evidence_text:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-config-not-mentioned",
                    "%s %s does not mention certified config %s"
                    % (claim.evidence_doc, claim.row_id, config_path),
                )
            )
    return issues


def _check_evidence_doc_config_fields(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure single-config evidence docs have a structured Config field."""
    configs_by_doc: dict[str, set[str]] = {}
    for claim in iter_ready_row_claims(root):
        if not claim.config_paths:
            continue
        configs_by_doc.setdefault(claim.evidence_doc, set()).update(claim.config_paths)

    issues = []
    test_results_by_doc = _test_result_artifacts_by_doc(artifacts)
    for evidence_doc, config_paths in sorted(configs_by_doc.items()):
        if len(config_paths) != 1 or len(test_results_by_doc.get(evidence_doc, [])) != 1:
            continue
        expected_config = next(iter(config_paths))
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        if expected_config not in evidence_text:
            continue
        fields = _evidence_table_fields(evidence_text)
        config_field = fields.get("Config", "")
        if not config_field:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-config-field-missing",
                    "%s references config %s but has no Config field"
                    % (evidence_doc, expected_config),
                )
            )
            continue
        field_configs = set(CONFIG_PATH_RE.findall(config_field))
        if config_field.startswith("configs/experiments/"):
            field_configs.add(config_field)
        if field_configs == {expected_config}:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-config-field-mismatch",
                "%s Config=%r but matrix references config %s"
                % (evidence_doc, config_field, expected_config),
            )
        )
    return issues


def _check_evidence_doc_row_mentions(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure release evidence docs explicitly name the ready rows they certify."""
    artifact_docs = {artifact.evidence_doc for artifact in artifacts}
    issues = []
    for claim in iter_ready_row_claims(root):
        if claim.evidence_doc not in artifact_docs:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        if _row_id_mentioned(evidence_text, claim.row_id):
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-row-id-not-mentioned",
                "%s does not mention ready matrix row %s"
                % (claim.evidence_doc, claim.row_id),
            )
        )
    return issues


def _check_evidence_doc_matrix_row_id_fields(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure explicit Matrix row ID fields match rows that reference the doc."""
    claims_by_doc: dict[str, set[str]] = {}
    for claim in iter_ready_row_claims(root):
        claims_by_doc.setdefault(claim.evidence_doc, set()).add(claim.row_id)

    issues = []
    test_results_by_doc = _test_result_artifacts_by_doc(artifacts)
    for evidence_doc, claim_rows in sorted(claims_by_doc.items()):
        if len(test_results_by_doc.get(evidence_doc, [])) != 1:
            continue
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        fields = _evidence_table_fields(evidence_text)
        matrix_row_id = fields.get("Matrix row ID", "")
        if not matrix_row_id:
            if not all(_row_id_mentioned(evidence_text, row_id) for row_id in claim_rows):
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-matrix-row-id-missing",
                    "%s references rows %s but has no Matrix row ID field"
                    % (evidence_doc, ", ".join(sorted(claim_rows))),
                )
            )
            continue
        field_rows = set(ROW_ID_RE.findall(matrix_row_id))
        if field_rows == claim_rows:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-matrix-row-id-mismatch",
                "%s Matrix row ID=%r but matrix references rows: %s"
                % (evidence_doc, matrix_row_id, ", ".join(sorted(claim_rows))),
            )
        )
    return issues


def _check_evidence_doc_suite_fields(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure explicit Suite fields match matrix suite references."""
    suites_by_doc: dict[str, set[str]] = {}
    for claim in iter_ready_row_claims(root):
        if not claim.suite_names:
            continue
        suites_by_doc.setdefault(claim.evidence_doc, set()).update(claim.suite_names)

    issues = []
    test_results_by_doc = _test_result_artifacts_by_doc(artifacts)
    for evidence_doc, matrix_suites in sorted(suites_by_doc.items()):
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        fields = _evidence_table_fields(evidence_text)
        suite_field = fields.get("Suite", "")
        if not suite_field:
            if len(matrix_suites) != 1 or len(test_results_by_doc.get(evidence_doc, [])) != 1:
                continue
            expected_suite = next(iter(matrix_suites))
            if not _suite_name_mentioned(evidence_text, expected_suite):
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-suite-field-missing",
                    "%s suite %s has one primary test-results artifact but no Suite field"
                    % (evidence_doc, expected_suite),
                )
            )
            continue
        evidence_suites = set(re.findall(r"[A-Za-z0-9_-]+", suite_field))
        if evidence_suites == matrix_suites:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-suite-field-mismatch",
                "%s Suite=%r but matrix references suites: %s"
                % (evidence_doc, suite_field, ", ".join(sorted(matrix_suites))),
            )
        )
    return issues


def _check_evidence_doc_command_fields(
    root: Path,
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure single-suite evidence docs have a structured Command field."""
    suites_by_doc: dict[str, set[str]] = {}
    for claim in iter_ready_row_claims(root):
        if not claim.suite_names:
            continue
        suites_by_doc.setdefault(claim.evidence_doc, set()).update(claim.suite_names)

    issues = []
    test_results_by_doc = _test_result_artifacts_by_doc(artifacts)
    for evidence_doc, matrix_suites in sorted(suites_by_doc.items()):
        if len(matrix_suites) != 1 or len(test_results_by_doc.get(evidence_doc, [])) != 1:
            continue
        expected_suite = next(iter(matrix_suites))
        expected_command = PRETAG_WRAPPER_COMMAND_BY_SUITE.get(expected_suite)
        if expected_command is None:
            continue
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        fields = _evidence_table_fields(evidence_path.read_text(encoding="utf-8"))
        suite_field = fields.get("Suite", "")
        evidence_suites = set(re.findall(r"[A-Za-z0-9_-]+", suite_field))
        if evidence_suites != matrix_suites:
            continue
        command_field = fields.get("Command", "")
        if not command_field:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-command-field-missing",
                    "%s suite %s has one primary test-results artifact but no "
                    "Command field" % (evidence_doc, expected_suite),
                )
            )
            continue
        if command_field == expected_command:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-command-field-mismatch",
                "%s Command=%r but suite %s expects %r"
                % (evidence_doc, command_field, expected_suite, expected_command),
            )
        )
    return issues


def _row_id_mentioned(text: str, row_id: str) -> bool:
    """Return whether text mentions a matrix row ID without prefix ambiguity."""
    pattern = r"(?<![A-Z0-9-])%s(?![A-Z0-9-])" % (re.escape(row_id),)
    return re.search(pattern, text) is not None


def _check_evidence_doc_commands(root: Path) -> list[EvidenceArtifactIssue]:
    """Ensure ready-row evidence docs record the wrapper commands for their suites."""
    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.suite_names:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        for suite_name in claim.suite_names:
            command = PRETAG_WRAPPER_COMMAND_BY_SUITE.get(suite_name)
            if command is None:
                issues.append(
                    EvidenceArtifactIssue(
                        "evidence-doc-suite-wrapper-unknown",
                        "%s %s uses suite %s but no wrapper command mapping exists"
                        % (claim.evidence_doc, claim.row_id, suite_name),
                    )
                )
                continue
            if command in evidence_text:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-command-missing-for-suite",
                    "%s %s uses suite %s but evidence does not record '%s'"
                    % (claim.evidence_doc, claim.row_id, suite_name, command),
                )
            )
    return issues


def _check_evidence_doc_wrapper_scenarios(root: Path) -> list[EvidenceArtifactIssue]:
    """Ensure ready-row evidence docs mention named wrapper scenarios."""
    issues = []
    for claim in iter_ready_row_claims(root):
        if not claim.wrapper_scenarios:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        for scenario in claim.wrapper_scenarios:
            if scenario in evidence_text:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-wrapper-scenario-missing",
                    "%s %s uses wrapper scenario %s but evidence does not mention it"
                    % (claim.evidence_doc, claim.row_id, scenario),
                )
            )
    return issues


def _check_subset_evidence_scope(root: Path) -> list[EvidenceArtifactIssue]:
    """Ensure software-only subset evidence cannot be read as full-row evidence."""
    issues = []
    for claim in iter_ready_row_claims(root):
        parent_row_id = _subset_parent_row_id(claim.row_id)
        if not parent_row_id:
            continue
        evidence_path = root / claim.evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        evidence_lower = evidence_text.lower().replace("`", "")
        expected_parent_scope = "does not certify parent row %s" % (parent_row_id.lower(),)
        if expected_parent_scope not in evidence_lower:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-subset-parent-scope-missing",
                    "%s %s must state that it does not certify parent row %s"
                    % (claim.evidence_doc, claim.row_id, parent_row_id),
                )
            )
        if not _has_subset_metric_nonclaim(evidence_text):
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-subset-metric-scope-missing",
                    "%s %s must state that image-classification metric artifacts "
                    "are not certified by the software-only subset evidence"
                    % (claim.evidence_doc, claim.row_id),
                )
            )

        fields = _evidence_table_fields(evidence_text)
        runtime_targets = fields.get("Runtime targets", "").lower()
        if "software" not in runtime_targets:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-subset-runtime-missing-software",
                    "%s %s is a software-only subset row but Runtime targets "
                    "does not include software" % (claim.evidence_doc, claim.row_id),
                )
            )
        if "application" not in runtime_targets:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-subset-runtime-includes-application",
                "%s %s is a subset row but Runtime targets includes application"
                % (claim.evidence_doc, claim.row_id),
            )
        )
    return issues


def _has_subset_metric_nonclaim(evidence_text: str) -> bool:
    """Return whether subset evidence explicitly excludes benchmark metric artifacts."""
    lines = evidence_text.lower().replace("`", "").splitlines()
    for index, line in enumerate(lines):
        if "metric artifact" not in line or "image-classification" not in line:
            continue
        context = "\n".join(lines[max(index - 8, 0) : index + 1])
        if "does not certify" in context or "not certify" in context:
            return True
    return False


def _check_artifact_audit_summary(
    root: Path,
    artifacts: list[EvidenceArtifact],
    issue_count_before_summary: int,
) -> list[EvidenceArtifactIssue]:
    """Validate evidence-doc summary fields for this artifact audit."""
    issues = []
    expected_fields = {
        "Command": ARTIFACT_AUDIT_COMMAND,
        "Primary artifacts checked": str(len(artifacts)),
        "Result": "TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=%d" % issue_count_before_summary,
    }

    for evidence_doc in iter_evidence_docs(root):
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        summary_required = any(
            line.strip().lower().startswith(ARTIFACT_AUDIT_SUMMARY_MARKER)
            for line in evidence_text.splitlines()
        )
        fields = (
            _evidence_section_table_fields(evidence_text, ARTIFACT_AUDIT_SUMMARY_MARKER)
            if summary_required
            else _evidence_table_fields(evidence_text)
        )
        checked_fields = (
            expected_fields
            if summary_required
            else {
                key: value
                for key, value in expected_fields.items()
                if key != "Command"
            }
        )
        for field, expected in checked_fields.items():
            if field not in fields:
                if summary_required:
                    issues.append(
                        EvidenceArtifactIssue(
                            "artifact-audit-summary-field-missing",
                            "%s missing %s" % (evidence_doc, field),
                        )
                    )
                continue
            if fields[field] == expected:
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "artifact-audit-summary-mismatch",
                    "%s %s=%r expected %r"
                    % (evidence_doc, field, fields[field], expected),
                )
            )
    return issues


def _check_evidence_doc_context(root: Path) -> list[EvidenceArtifactIssue]:
    """Validate source, runner, and command context in release evidence docs."""
    issues = []
    for evidence_doc in iter_evidence_docs(root):
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        text = evidence_path.read_text(encoding="utf-8")
        fields = _evidence_table_fields(text)
        for field in REQUIRED_EVIDENCE_CONTEXT_FIELDS:
            if fields.get(field):
                continue
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-context-field-missing",
                    "%s missing %s" % (evidence_doc, field),
                )
            )
        git_commit = fields.get("Git commit", "")
        if git_commit and not GIT_COMMIT_RE.match(git_commit):
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-git-commit-invalid",
                    "%s Git commit=%r is not a 7-40 character hexadecimal commit"
                    % (evidence_doc, git_commit),
                )
            )
        date = fields.get("Date", "")
        if date and not DATE_RE.match(date):
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-date-invalid",
                    "%s Date=%r must use YYYY-MM-DD" % (evidence_doc, date),
                )
            )
        filename_date_match = EVIDENCE_DOC_DATE_RE.search(evidence_doc)
        if date and DATE_RE.match(date) and filename_date_match:
            filename_date = filename_date_match.group(1)
            if date != filename_date:
                issues.append(
                    EvidenceArtifactIssue(
                        "evidence-doc-date-filename-mismatch",
                        "%s Date=%r does not match filename date %s"
                        % (evidence_doc, date, filename_date),
                    )
                )
        if not fields.get("Runner context") and not fields.get("Runner user"):
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-runner-context-missing",
                    "%s missing Runner context or Runner user" % (evidence_doc,),
                )
            )
        if not fields.get("Provider / host prerequisites"):
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-prerequisites-missing",
                    "%s missing Provider / host prerequisites" % (evidence_doc,),
                )
            )
        if not fields.get("Command") and "\nCommand:\n" not in text:
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-command-missing",
                    "%s missing command field or command block" % (evidence_doc,),
                )
            )
        if not _has_limitations_scope(text):
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-limitations-missing",
                    "%s missing limitations or non-certification scope" % (evidence_doc,),
                )
            )
        if not _has_runtime_scope(fields):
            issues.append(
                EvidenceArtifactIssue(
                    "evidence-doc-runtime-scope-missing",
                    "%s missing Runtime targets field" % (evidence_doc,),
                )
            )
    return issues


def _check_evidence_docs_single_git_commit(root: Path) -> list[EvidenceArtifactIssue]:
    """Ensure the referenced evidence set records one coherent source commit."""
    docs_by_commit: dict[str, list[str]] = {}
    for evidence_doc in iter_evidence_docs(root):
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            continue
        fields = _evidence_table_fields(evidence_path.read_text(encoding="utf-8"))
        git_commit = fields.get("Git commit", "")
        if not GIT_COMMIT_RE.match(git_commit):
            continue
        docs_by_commit.setdefault(git_commit, []).append(evidence_doc)

    if len(docs_by_commit) <= 1:
        return []

    commit_parts = [
        "%s in %s" % (commit, ", ".join(sorted(docs)))
        for commit, docs in sorted(docs_by_commit.items())
    ]
    return [
        EvidenceArtifactIssue(
            "evidence-doc-source-commit-mismatch",
            "release evidence docs must use one Git commit; found %s"
            % ("; ".join(commit_parts),),
        )
    ]


def _check_test_result_dates_match_evidence_docs(
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure retained VM test-result dates match their evidence document date."""
    issues = []
    for artifact in artifacts:
        if artifact.kind != "test-results":
            continue
        fields = _evidence_table_fields(artifact.evidence_path.read_text(encoding="utf-8"))
        evidence_date = fields.get("Date", "")
        if not DATE_RE.match(evidence_date):
            continue
        timestamp = _test_results_filename_timestamp(artifact.path)
        if not timestamp:
            continue
        artifact_date = timestamp[:10]
        if artifact_date == evidence_date:
            continue
        issues.append(
            EvidenceArtifactIssue(
                "test-results-date-evidence-date-mismatch",
                "%s references %s dated %s but evidence Date=%s"
                % (artifact.evidence_doc, artifact.path, artifact_date, evidence_date),
            )
            )
    return issues


def _check_evidence_doc_runner_context_fields(
    artifacts: list[EvidenceArtifact],
) -> list[EvidenceArtifactIssue]:
    """Ensure single-run evidence docs have a structured Runner context field."""
    issues = []
    for evidence_doc, test_results in sorted(_test_result_artifacts_by_doc(artifacts).items()):
        if len(test_results) != 1:
            continue
        artifact = test_results[0]
        fields = _evidence_table_fields(artifact.evidence_path.read_text(encoding="utf-8"))
        if fields.get("Runner context"):
            continue
        issues.append(
            EvidenceArtifactIssue(
                "evidence-doc-runner-context-field-missing",
                "%s has one primary test-results artifact %s but no Runner context field"
                % (evidence_doc, artifact.path),
            )
        )
    return issues


def _has_limitations_scope(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "## limitations",
            "does not certify",
            "not certify",
            "not for final replacement",
            "not a final replacement",
        )
    )


def _has_runtime_scope(fields: dict[str, str]) -> bool:
    return bool(fields.get("Runtime targets"))


def find_artifact_issues(root: Path = ROOT) -> list[EvidenceArtifactIssue]:
    """Return local release evidence artifact issues."""
    root = root.resolve()
    artifacts = extract_primary_artifacts(root)
    issues: list[EvidenceArtifactIssue] = []
    if not artifacts:
        issues.append(
            EvidenceArtifactIssue("artifact-none-found", "No primary evidence artifacts found")
        )
        return issues

    for artifact in artifacts:
        issues.extend(check_artifact(artifact))
    issues.extend(_check_evidence_doc_context(root))
    issues.extend(_check_evidence_doc_runner_context_fields(artifacts))
    issues.extend(_check_evidence_docs_single_git_commit(root))
    issues.extend(_check_test_result_dates_match_evidence_docs(artifacts))
    issues.extend(_check_evidence_docs_have_primary_artifacts(root, artifacts))
    issues.extend(_check_specialized_artifact_links(artifacts))
    issues.extend(_check_cloud_audit_ready_suite_prereqs(root, artifacts))
    issues.extend(_check_cloud_audit_all_parity_suite_prereqs(root, artifacts))
    issues.extend(_check_cloud_audit_latest_report(root, artifacts))
    issues.extend(_check_claimed_config_results(root, artifacts))
    issues.extend(_check_evidence_doc_row_mentions(root, artifacts))
    issues.extend(_check_evidence_doc_matrix_row_id_fields(root, artifacts))
    issues.extend(_check_evidence_doc_suite_fields(root, artifacts))
    issues.extend(_check_evidence_doc_command_fields(root, artifacts))
    issues.extend(_check_evidence_doc_config_mentions(root))
    issues.extend(_check_evidence_doc_config_fields(root, artifacts))
    issues.extend(_check_evidence_doc_profile_mentions(root))
    issues.extend(_check_evidence_doc_profile_fields(root, artifacts))
    issues.extend(_check_evidence_doc_result_summary_path_fields(artifacts))
    issues.extend(_check_evidence_doc_required_artifact_fields(artifacts))
    issues.extend(_check_evidence_doc_artifact_root_fields(artifacts))
    issues.extend(_check_evidence_doc_runtime_targets_match_configs(root))
    issues.extend(_check_evidence_doc_runtime_target_claims_have_support(root, artifacts))
    issues.extend(_check_benchmark_application_evidence(root, artifacts))
    issues.extend(_check_network_emulation_evidence(root, artifacts))
    issues.extend(_check_claimed_stdout_markers(root, artifacts))
    issues.extend(_check_evidence_doc_provider_prereqs_match_configs(root))
    issues.extend(_check_evidence_doc_cleanup_claims(root, artifacts))
    issues.extend(_check_evidence_doc_commands(root))
    issues.extend(_check_evidence_doc_wrapper_scenarios(root))
    issues.extend(_check_subset_evidence_scope(root))
    issues.extend(_check_artifact_audit_summary(root, artifacts, len(issues)))
    return issues


def main() -> int:
    """Run the local release evidence artifact audit."""
    artifacts = extract_primary_artifacts(ROOT)
    issues: list[EvidenceArtifactIssue] = []
    for artifact in artifacts:
        artifact_issues = check_artifact(artifact)
        if artifact_issues:
            issues.extend(artifact_issues)
            print("FAIL %s %s" % (artifact.kind, artifact.path))
        else:
            print("OK %s %s" % (artifact.kind, artifact.path))
    issues.extend(_check_evidence_doc_context(ROOT))
    issues.extend(_check_evidence_doc_runner_context_fields(artifacts))
    issues.extend(_check_evidence_docs_single_git_commit(ROOT))
    issues.extend(_check_test_result_dates_match_evidence_docs(artifacts))
    issues.extend(_check_evidence_docs_have_primary_artifacts(ROOT, artifacts))
    issues.extend(_check_specialized_artifact_links(artifacts))
    issues.extend(_check_cloud_audit_ready_suite_prereqs(ROOT, artifacts))
    issues.extend(_check_cloud_audit_all_parity_suite_prereqs(ROOT, artifacts))
    issues.extend(_check_cloud_audit_latest_report(ROOT, artifacts))
    issues.extend(_check_claimed_config_results(ROOT, artifacts))
    issues.extend(_check_evidence_doc_row_mentions(ROOT, artifacts))
    issues.extend(_check_evidence_doc_matrix_row_id_fields(ROOT, artifacts))
    issues.extend(_check_evidence_doc_suite_fields(ROOT, artifacts))
    issues.extend(_check_evidence_doc_command_fields(ROOT, artifacts))
    issues.extend(_check_evidence_doc_config_mentions(ROOT))
    issues.extend(_check_evidence_doc_config_fields(ROOT, artifacts))
    issues.extend(_check_evidence_doc_profile_mentions(ROOT))
    issues.extend(_check_evidence_doc_profile_fields(ROOT, artifacts))
    issues.extend(_check_evidence_doc_result_summary_path_fields(artifacts))
    issues.extend(_check_evidence_doc_required_artifact_fields(artifacts))
    issues.extend(_check_evidence_doc_artifact_root_fields(artifacts))
    issues.extend(_check_evidence_doc_runtime_targets_match_configs(ROOT))
    issues.extend(_check_evidence_doc_runtime_target_claims_have_support(ROOT, artifacts))
    issues.extend(_check_benchmark_application_evidence(ROOT, artifacts))
    issues.extend(_check_network_emulation_evidence(ROOT, artifacts))
    issues.extend(_check_claimed_stdout_markers(ROOT, artifacts))
    issues.extend(_check_evidence_doc_provider_prereqs_match_configs(ROOT))
    issues.extend(_check_evidence_doc_cleanup_claims(ROOT, artifacts))
    issues.extend(_check_evidence_doc_commands(ROOT))
    issues.extend(_check_evidence_doc_wrapper_scenarios(ROOT))
    issues.extend(_check_subset_evidence_scope(ROOT))
    issues.extend(_check_artifact_audit_summary(ROOT, artifacts, len(issues)))

    if not artifacts:
        issues.append(
            EvidenceArtifactIssue("artifact-none-found", "No primary evidence artifacts found")
        )

    for issue in issues:
        print("%s: %s" % (issue.kind, issue.detail))
    print("TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=%d" % (len(issues)))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
