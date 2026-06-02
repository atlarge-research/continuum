#!/usr/bin/env python3
"""Check release certification matrix coverage against repo inventories."""

# pylint: disable=too-many-lines

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
OLD_MAIN_REF = "origin/main"
MATRIX_PATH = Path("docs/release_certification_matrix.md")
NOTES_PATH = Path("docs/release_notes_m1_draft.md")
PARITY_BACKLOG_PATH = Path("docs/old_main_parity_issue_seed.md")
PLAN_STACK_PATH = Path("docs/rework_plan_stack.md")
TEST_CONFIG_PATH = Path("scripts/test/test_config.json")
EVIDENCE_RE = re.compile(r"`(docs/release_evidence_[^`]+\.md)`")
CONFIG_PATH_RE = re.compile(
    r"`((?:configs/experiments|configuration/tests)/[^`]+?\.(?:cfg|ya?ml))`"
)
ROW_ID_RE = re.compile(r"`((?:M\d+|P)-[A-Z0-9-]+)`")
ROW_RANGE_RE = re.compile(r"`(P-[A-Z]+-\d+)`\s+through\s+`(P-[A-Z]+-\d+)`")
SUBSET_ROW_RE = re.compile(r"^(P-[A-Z]+-\d+)-(?:SW|SW-LOCAL)$")
SUITE_REF_RE = re.compile(r"\bsuite\s+`([^`]+)`")
STATUS_LABEL_RE = re.compile(r"`([^`]+)`")
NUMBERED_COMMAND_RE = re.compile(r"^(\d+)\.\s+`([^`]+)`")
ALLOWED_STATUS_LABELS = {
    "core-ready",
    "certified",
    "certified-candidate",
    "ported-unverified",
    "historical",
    "deprecated-proposed",
}
EVIDENCE_REQUIRED_STATUS_LABELS = {"core-ready", "certified"}
REQUIRED_CLOUD_AUDIT_GATES = (
    "compile sweep",
    "cloud audit shell syntax check",
    "smoke wrapper shell syntax check",
    "host setup shell syntax check",
    "git diff whitespace check",
    "unit unittest discovery",
    "e2e unittest discovery",
    "combined unittest discovery",
    "docs path reference check",
    "public release-claims check",
    "release certification matrix check",
    "configured suite catalog",
)
REQUIRED_M1_PRE_TAG_COMMANDS = (
    "scripts/test/run_cloud_static_audit.sh",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit",
    "python3 scripts/test/check_release_pretag.py",
    "python3 scripts/test/check_release_claims.py",
    "python3 scripts/test/check_release_matrix.py",
    "python3 scripts/test/check_docs_paths.py",
    "git diff --check",
    "sudo -n /usr/local/bin/continuum-hostctl sync-repo",
    "sudo -n /usr/local/bin/continuum-hostctl verify",
    "sh scripts/test/setup_agent_host.sh verify",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity",
    "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_local_parity",
)
REQUIRED_M1_HOST_SEQUENCE_COMMANDS = (
    "scripts/test/run_cloud_static_audit.sh",
    "sudo -n /usr/local/bin/continuum-hostctl sync-repo",
    "sudo -n /usr/local/bin/continuum-hostctl verify",
    "sh scripts/test/setup_agent_host.sh verify",
)
REQUIRED_EVIDENCE_TEMPLATE_FIELDS = (
    "Matrix row ID",
    "Git commit",
    "Tree state",
    "Date",
    "Runner context",
    "Command",
    "Provider / host prerequisites",
    "Config",
    "Suite",
    "Provider profile",
    "Software profile",
    "Runtime targets",
    "Required artifacts checked",
    "Result summary path",
    "Artifact root",
    "Limitations",
)
REQUIRED_PLAN_STACK_REFERENCES = (
    Path("docs/rework_milestone_release_plan.md"),
    MATRIX_PATH,
    Path("docs/post_release_roadmap.md"),
)
REQUIRED_PLAN_STACK_BOUNDARIES = (
    (
        "core-module-boundary",
        ("core/module boundary", "provider/software/application stacks are modules"),
        "must keep the core/module boundary as a locked decision",
    ),
    (
        "qemu-provider-module",
        ("qemu", "provider module", "must not be described as", "core"),
        "must state that qemu is a provider module, not Continuum core",
    ),
    (
        "runtime-evidence-required",
        ("runtime claims require", "vm-backed or cloud-backed evidence"),
        "must state that runtime claims require VM-backed or cloud-backed evidence",
    ),
    (
        "intermediate-before-final",
        ("intermediate rework milestones", "final", "main", "replacement"),
        "must distinguish intermediate milestones from final main replacement",
    ),
    (
        "old-main-parity-gate",
        ("old-main parity", "explicit deprecation"),
        "must keep old-main parity or explicit deprecation as the final replacement gate",
    ),
)
REQUIRED_PARITY_BACKLOG_CONVERSION_MARKERS = (
    (
        "one-issue-per-row",
        ("one issue per matrix row",),
        "conversion notes must keep one issue per matrix row as the default",
    ),
    (
        "row-id-in-title",
        ("row id", "issue title"),
        "conversion notes must require the row ID in the issue title",
    ),
    (
        "matrix-action-copy",
        ("copy the certification action", "release_certification_matrix.md"),
        "conversion notes must carry the matrix certification action into issues",
    ),
    (
        "fresh-runtime-evidence",
        ("fresh vm-backed or cloud-backed evidence", "certified"),
        "conversion notes must require fresh runtime evidence before certification",
    ),
    (
        "synchronized-docs",
        ("update the matrix", "release notes", "this seed"),
        "conversion notes must keep matrix, release notes, and seed synchronized",
    ),
)
PRETAG_WRAPPER_COMMAND_BY_SUITE = {
    "smoke": "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression",
    "benchmark_smoke": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression"
    ),
    "network_validation": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation"
    ),
    "qemu_infra_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity"
    ),
    "qemu_k8s_nobench_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity"
    ),
    "qemu_k8s_image_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_image_parity"
    ),
    "qemu_kubeedge_software_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
        "qemu_kubeedge_software_parity"
    ),
    "qemu_kubeedge_image_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
        "qemu_kubeedge_image_parity"
    ),
    "qemu_mist_software_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity"
    ),
    "qemu_mist_image_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_image_parity"
    ),
    "qemu_endpoint_software_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
        "qemu_endpoint_software_parity"
    ),
    "qemu_endpoint_image_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
        "qemu_endpoint_image_parity"
    ),
    "qemu_openfaas_software_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
        "qemu_openfaas_software_parity"
    ),
    "qemu_openfaas_image_local_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
        "qemu_openfaas_image_local_parity"
    ),
    "qemu_openfaas_image_parity": (
        "sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke "
        "qemu_openfaas_image_parity"
    ),
}


@dataclass(frozen=True)
class MatrixIssue:
    """A release-matrix drift issue."""

    kind: str
    detail: str


def _repo_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _matrix_text(root: Path) -> str:
    return (root / MATRIX_PATH).read_text(encoding="utf-8")


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _primary_status_label(status_cell: str) -> str:
    match = STATUS_LABEL_RE.search(status_cell)
    if not match:
        return ""
    return match.group(1)


def iter_legacy_test_configs(root: Path) -> Iterable[str]:
    """Yield legacy test config paths that need matrix disposition."""
    for path in sorted((root / "configuration" / "tests").glob("*/*.cfg")):
        yield _repo_rel(path, root)


def _git_command(root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        text=True,
    )


def _is_git_work_tree(root: Path) -> bool:
    """Return whether root is inside a git worktree."""
    result = _git_command(root, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _old_main_ref_available(root: Path) -> bool:
    """Return whether the local old-main ref is available for parity inventory."""
    result = _git_command(root, ["rev-parse", "--verify", "%s^{commit}" % (OLD_MAIN_REF,)])
    return result.returncode == 0


def iter_old_main_legacy_test_configs(root: Path) -> Iterable[str]:
    """Yield legacy test config paths from the local old-main git reference."""
    result = _git_command(
        root,
        [
            "ls-tree",
            "-r",
            "--name-only",
            OLD_MAIN_REF,
            "--",
            "configuration/tests",
        ],
    )
    if result.returncode != 0:
        return
    for line in sorted(result.stdout.splitlines()):
        if line.endswith(".cfg"):
            yield line


def iter_parity_yaml(root: Path) -> Iterable[str]:
    """Yield YAML parity configs that should be referenced by the matrix."""
    parity_root = root / "configs" / "experiments" / "parity"
    if not parity_root.exists():
        return
    for path in sorted(parity_root.rglob("*.yaml")):
        yield _repo_rel(path, root)


def iter_parity_suites(root: Path) -> Iterable[str]:
    """Yield test suites whose configured directories are parity experiment roots."""
    for suite_name, directories in _suite_directories(root).items():
        if any(
            isinstance(directory, str)
            and directory.startswith("configs/experiments/parity/")
            for directory in directories
        ):
            yield suite_name


def _old_main_table_rows(text: str) -> Iterable[list[str]]:
    in_table = False
    for line in text.splitlines():
        if line.startswith("## 4. Old-Main Provider And Topology Parity"):
            in_table = True
            continue
        if in_table and line.startswith("## 5. "):
            return
        if in_table and line.startswith("| P-"):
            yield _markdown_cells(line)


def _claim_rows(text: str) -> Iterable[tuple[str, str, str]]:
    """Yield row id, status cell, and action cell for concrete claim rows."""
    for cells in _claim_table_rows(text):
        if len(cells) < 6:
            yield (cells[0] if cells else "<unknown>", "", " | ".join(cells))
            continue
        yield cells[0], cells[4], cells[5]


def _claim_table_rows(text: str) -> Iterable[list[str]]:
    """Yield parsed markdown cells for concrete M1 and parity claim rows."""
    for line in text.splitlines():
        if not line.startswith("| M1-") and not line.startswith("| P-"):
            continue
        yield _markdown_cells(line)


def _suite_directories(root: Path) -> dict[str, list[str]]:
    with (root / TEST_CONFIG_PATH).open("r", encoding="utf-8") as filep:
        test_config = json.load(filep)
    return {
        suite_name: [
            directory
            for directory in suite_config.get("directories", [])
            if isinstance(directory, str)
        ]
        for suite_name, suite_config in sorted(test_config.get("test_suites", {}).items())
    }


def _claim_row_statuses(text: str) -> dict[str, str]:
    """Return matrix row IDs and their normalized status labels."""
    return {
        row_id: _primary_status_label(status)
        for row_id, status, _action in _claim_rows(text)
    }


def _ready_row_suite_refs(text: str) -> Iterable[tuple[str, str]]:
    """Yield ready matrix row IDs and their referenced test suites."""
    for cells in _claim_table_rows(text):
        if len(cells) < 5:
            continue
        status_label = _primary_status_label(cells[4])
        if status_label not in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue
        row_id = cells[0]
        row_text = " | ".join(cells)
        for suite_name in sorted(set(SUITE_REF_RE.findall(row_text))):
            yield row_id, suite_name


def _row_id_from_cell(cell: str) -> str:
    """Return a matrix row ID from a markdown table cell."""
    match = ROW_ID_RE.search(cell)
    if match:
        return match.group(1)
    return cell.strip("`")


def _claim_row_evidence_paths(text: str) -> Iterable[tuple[str, str]]:
    """Yield matrix row IDs with release-evidence docs named in their action cell."""
    for row_id, status, action in _claim_rows(text):
        if _primary_status_label(status) not in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue
        for evidence_path in EVIDENCE_RE.findall(action):
            yield row_id, evidence_path


def _subset_parent_row_id(row_id: str) -> str:
    match = SUBSET_ROW_RE.match(row_id)
    return match.group(1) if match else ""


def _subset_row_scope_issues(text: str) -> list[MatrixIssue]:
    """Validate that software-only subset rows cannot be mistaken for full rows."""
    issues = []
    rows_by_id = {
        cells[0]: cells
        for cells in _claim_table_rows(text)
        if cells
    }
    for row_id, cells in sorted(rows_by_id.items()):
        parent_row_id = _subset_parent_row_id(row_id)
        if not parent_row_id:
            continue
        if parent_row_id not in rows_by_id:
            issues.append(
                MatrixIssue(
                    "subset-row-parent-missing",
                    "%s is a subset row but parent row %s is absent from the matrix"
                    % (row_id, parent_row_id),
                )
            )

        legacy_cell = cells[1] if len(cells) >= 2 else ""
        if "subset of" not in legacy_cell.lower():
            issues.append(
                MatrixIssue(
                    "subset-row-legacy-scope-missing",
                    "%s must describe its legacy scope as a subset of %s"
                    % (row_id, parent_row_id),
                )
            )

        action_cell = cells[5] if len(cells) >= 6 else " | ".join(cells)
        action_lower = action_cell.lower()
        if "does not certify" in action_lower and parent_row_id in action_cell:
            continue
        issues.append(
            MatrixIssue(
                "subset-row-noncertification-missing",
                "%s must state that it does not certify parent row %s"
                % (row_id, parent_row_id),
            )
        )
    return issues


def _module_backlog_status_cells(text: str) -> Iterable[tuple[str, str]]:
    in_table = False
    for line in text.splitlines():
        if line.startswith("## 5. Module Certification Backlog"):
            in_table = True
            continue
        if in_table and line.startswith("## 6. "):
            return
        if in_table and line.startswith("| `"):
            cells = _markdown_cells(line)
            if len(cells) >= 3:
                yield cells[0], cells[2]


def _module_names_from_cell(cell: str) -> list[str]:
    """Return module names from a module-backlog row name cell."""
    return [module_name.strip() for module_name in STATUS_LABEL_RE.findall(cell)]


def _status_label_issues(text: str) -> list[MatrixIssue]:
    issues = []
    for row_id, status, _action in _claim_rows(text):
        status_label = _primary_status_label(status)
        if not status_label:
            issues.append(MatrixIssue("claim-row-missing-status", row_id))
            continue
        if status_label not in ALLOWED_STATUS_LABELS:
            issues.append(
                MatrixIssue(
                    "claim-row-invalid-status",
                    "%s uses unknown status '%s'" % (row_id, status_label),
                )
            )
    for row_id, status in _module_backlog_status_cells(text):
        status_label = _primary_status_label(status)
        if not status_label:
            issues.append(MatrixIssue("module-row-missing-status", row_id))
            continue
        if status_label not in ALLOWED_STATUS_LABELS:
            issues.append(
                MatrixIssue(
                    "module-row-invalid-status",
                    "%s uses unknown status '%s'" % (row_id, status_label),
                )
            )
    return issues


def _module_backlog_certified_row_issues(text: str) -> list[MatrixIssue]:
    """Validate that module-backlog certified row references are ready rows."""
    row_statuses = _claim_row_statuses(text)
    issues = []
    for module_name, status_cell in _module_backlog_status_cells(text):
        status_label = _primary_status_label(status_cell)
        if status_label not in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue
        for row_id in sorted(_row_ids_in_text(status_cell)):
            row_status = row_statuses.get(row_id)
            if row_status is None:
                issues.append(
                    MatrixIssue(
                        "module-row-certified-unknown-row",
                        "%s claims certified row %s but that row is absent from the matrix"
                        % (module_name, row_id),
                    )
                )
                continue
            if row_status in EVIDENCE_REQUIRED_STATUS_LABELS:
                continue
            issues.append(
                MatrixIssue(
                    "module-row-certified-unready-row",
                    "%s claims certified row %s but matrix status is '%s'"
                    % (module_name, row_id, row_status),
                )
            )
    return issues


def _claim_action_closure_issues(text: str) -> list[MatrixIssue]:
    """Validate that non-ready parity matrix rows say how they can close."""
    issues = []
    for row_id, status, action in _claim_rows(text):
        status_label = _primary_status_label(status)
        if not row_id.startswith("P-") or status_label not in ALLOWED_STATUS_LABELS:
            continue
        if status_label in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue
        if _has_evidence_or_disposition_closure_path(action):
            continue
        issues.append(
            MatrixIssue(
                "claim-row-closure-path-missing",
                "%s action must require fresh evidence or an explicit "
                "historical/deprecation disposition" % (row_id,),
            )
        )
    return issues


def _is_under_directory(path: str, directory: str) -> bool:
    directory_prefix = directory.rstrip("/") + "/"
    return path.startswith(directory_prefix)


def _claim_reference_issues(root: Path, text: str) -> list[MatrixIssue]:
    """Validate matrix config and suite references against repository inventories."""
    issues = []
    suite_directories = _suite_directories(root)

    for cells in _claim_table_rows(text):
        row_id = cells[0] if cells else "<unknown>"
        reference_cells = cells[1:4]
        config_paths = sorted(
            {
                config_path
                for cell in reference_cells
                for config_path in CONFIG_PATH_RE.findall(cell)
            }
        )
        suite_names = sorted(
            {
                suite_name
                for cell in reference_cells
                for suite_name in SUITE_REF_RE.findall(cell)
            }
        )

        for config_path in config_paths:
            if not (root / config_path).exists():
                issues.append(
                    MatrixIssue(
                        "claim-row-config-missing",
                        "%s references missing %s" % (row_id, config_path),
                    )
                )

        experiment_configs = [
            config_path
            for config_path in config_paths
            if config_path.startswith("configs/experiments/")
        ]
        for suite_name in suite_names:
            directories = suite_directories.get(suite_name)
            if directories is None:
                issues.append(
                    MatrixIssue(
                        "claim-row-unknown-suite",
                        "%s references unknown suite %s" % (row_id, suite_name),
                    )
                )
                continue

            missing_directories = [
                directory for directory in directories if not (root / directory).exists()
            ]
            for directory in missing_directories:
                issues.append(
                    MatrixIssue(
                        "claim-row-suite-directory-missing",
                        "%s suite %s references missing directory %s"
                        % (row_id, suite_name, directory),
                    )
                )

            if not experiment_configs:
                continue
            if any(
                _is_under_directory(config_path, directory)
                for config_path in experiment_configs
                for directory in directories
            ):
                continue
            issues.append(
                MatrixIssue(
                    "claim-row-suite-config-mismatch",
                    "%s suite %s does not cover any referenced experiment config"
                    % (row_id, suite_name),
                )
            )

    return issues


def _certified_row_scope_issues(text: str) -> list[MatrixIssue]:
    """Ensure runtime-certified rows name exact rework configs and suites."""
    issues = []
    for cells in _claim_table_rows(text):
        if len(cells) < 5:
            continue
        row_id = cells[0]
        status_label = _primary_status_label(cells[4])
        if status_label != "certified":
            continue

        reference_text = " | ".join(cells[1:4])
        rework_configs = [
            config_path
            for config_path in CONFIG_PATH_RE.findall(reference_text)
            if config_path.startswith("configs/experiments/")
        ]
        if not rework_configs:
            issues.append(
                MatrixIssue(
                    "certified-row-config-missing",
                    "%s is certified but names no rework experiment config" % (row_id,),
                )
            )

        if SUITE_REF_RE.search(reference_text):
            continue
        issues.append(
            MatrixIssue(
                "certified-row-suite-missing",
                "%s is certified but names no runner suite" % (row_id,),
            )
        )
    return issues


def section_text(text: str, heading: str) -> str:
    """Return text below a second-level heading until the next second-level heading."""
    collecting = False
    lines = []
    for line in text.splitlines():
        if line.startswith("## "):
            if collecting:
                return "\n".join(lines).strip()
            collecting = line.strip() == heading
            continue
        if collecting:
            lines.append(line)
    return "\n".join(lines).strip()


def _evidence_template_issues(text: str) -> list[MatrixIssue]:
    """Validate that the evidence template names checker-enforced fields."""
    template_section = section_text(text, "## 6. Evidence Record Template")
    if not template_section:
        return []

    template_fields = set()
    for line in template_section.splitlines():
        if not line.startswith("|"):
            continue
        cells = _markdown_cells(line)
        if len(cells) < 2 or cells[0] in {"Field", "---"}:
            continue
        template_fields.add(cells[0].replace("`", "").strip())

    issues = []
    for field in REQUIRED_EVIDENCE_TEMPLATE_FIELDS:
        if field in template_fields:
            continue
        issues.append(
            MatrixIssue(
                "evidence-template-field-missing",
                "section 6 evidence template is missing '%s'" % (field,),
            )
        )
    return issues


def _planning_stack_issues(root: Path) -> list[MatrixIssue]:
    """Validate M0 release-planning boundaries are anchored in the plan stack."""
    plan_stack_path = root / PLAN_STACK_PATH
    if not plan_stack_path.exists():
        return [MatrixIssue("planning-stack-missing", PLAN_STACK_PATH.as_posix())]

    text = plan_stack_path.read_text(encoding="utf-8")
    normalized = _normalize_release_notes_text(text)
    issues = []
    for reference in REQUIRED_PLAN_STACK_REFERENCES:
        if reference.as_posix() in text:
            continue
        issues.append(
            MatrixIssue(
                "planning-stack-release-reference-missing",
                "%s must reference %s" % (PLAN_STACK_PATH.as_posix(), reference.as_posix()),
            )
        )

    for boundary_id, markers, detail in REQUIRED_PLAN_STACK_BOUNDARIES:
        if all(marker in normalized for marker in markers):
            continue
        issues.append(
            MatrixIssue(
                "planning-stack-release-boundary-missing",
                "%s: %s" % (boundary_id, detail),
            )
        )
    return issues


def pretag_command_order_messages(
    pre_tag_section: str,
    commands: tuple[str, ...] = REQUIRED_M1_PRE_TAG_COMMANDS,
) -> list[str]:
    """Return ordering drift messages for a pre-tag command section."""
    command_positions = {
        command: pre_tag_section.find(command)
        for command in commands
        if command in pre_tag_section
    }
    messages = []
    for previous_command, next_command in zip(commands, commands[1:]):
        if previous_command not in command_positions or next_command not in command_positions:
            continue
        if command_positions[previous_command] < command_positions[next_command]:
            continue
        messages.append(
            "section 7 lists '%s' before '%s'; keep pre-tag commands in "
            "documented order" % (next_command, previous_command)
        )
    return messages


def pretag_command_duplicate_messages(
    pre_tag_section: str,
    commands: tuple[str, ...] = REQUIRED_M1_PRE_TAG_COMMANDS,
) -> list[str]:
    """Return duplicate command messages for a pre-tag command section."""
    messages = []
    for command in commands:
        count = pre_tag_section.count(command)
        if count <= 1:
            continue
        messages.append(
            "section 7 lists '%s' %d times; keep one canonical pre-tag command"
            % (command, count)
        )
    return messages


def _expand_row_id_range(start_id: str, end_id: str) -> set[str]:
    """Expand simple same-prefix matrix ranges such as P-QEMU-01 through P-QEMU-04."""
    start_match = re.match(r"^(P-[A-Z]+-)(\d+)$", start_id)
    end_match = re.match(r"^(P-[A-Z]+-)(\d+)$", end_id)
    if not start_match or not end_match:
        return {start_id, end_id}
    if start_match.group(1) != end_match.group(1):
        return {start_id, end_id}

    start_number = int(start_match.group(2))
    end_number = int(end_match.group(2))
    if start_number > end_number:
        return {start_id, end_id}

    width = max(len(start_match.group(2)), len(end_match.group(2)))
    return {
        "%s%0*d" % (start_match.group(1), width, number)
        for number in range(start_number, end_number + 1)
    }


def _row_ids_in_text(text: str) -> set[str]:
    """Return matrix row IDs named in a markdown fragment, expanding simple ranges."""
    row_ids = set(ROW_ID_RE.findall(text))
    for start_id, end_id in ROW_RANGE_RE.findall(text):
        row_ids.update(_expand_row_id_range(start_id, end_id))
    return row_ids


def _release_notes_issues(root: Path, matrix_text: str) -> list[MatrixIssue]:
    """Return drift issues between the release matrix and M1 release-notes draft."""
    notes_path = root / NOTES_PATH
    if not notes_path.exists():
        return [MatrixIssue("release-notes-missing", NOTES_PATH.as_posix())]

    notes_text = notes_path.read_text(encoding="utf-8")
    release_type_section = section_text(notes_text, "## 1. Release Type")
    certification_section = section_text(notes_text, "## 3. What This Milestone Certifies")
    nonclaim_section = section_text(notes_text, "## 4. What This Milestone Does Not Certify")
    limitations_section = section_text(notes_text, "## 5. Known Limitations")
    evidence_section = section_text(notes_text, "## 2. Primary Evidence")
    pre_tag_section = section_text(notes_text, "## 7. Pre-Tag Gate")

    issues = []
    release_type_normalized = _normalize_release_notes_text(release_type_section)
    if not _states_intermediate_release(release_type_normalized):
        issues.append(
            MatrixIssue(
                "release-notes-type-intermediate-missing",
                "section 1 must describe M1 as an intermediate milestone or pre-release",
            )
        )
    if not _states_not_final_replacement(release_type_normalized):
        issues.append(
            MatrixIssue(
                "release-notes-final-replacement-denial-missing",
                "section 1 must state that M1 is not a final replacement for old main",
            )
        )

    if "`%s`" % (MATRIX_PATH.as_posix(),) not in evidence_section:
        issues.append(
            MatrixIssue(
                "release-notes-matrix-evidence-missing",
                "section 2 must list %s as primary evidence" % (MATRIX_PATH.as_posix(),),
            )
        )

    all_row_statuses = _claim_row_statuses(matrix_text)
    row_statuses = {
        row_id: status_label
        for row_id, status_label in all_row_statuses.items()
        if status_label in ALLOWED_STATUS_LABELS
    }
    ready_rows = {
        row_id
        for row_id, status_label in row_statuses.items()
        if status_label in EVIDENCE_REQUIRED_STATUS_LABELS
    }

    certified_note_rows = _row_ids_in_text(certification_section)
    for row_id in sorted(certified_note_rows - set(all_row_statuses)):
        issues.append(
            MatrixIssue(
                "release-notes-unknown-row-claimed",
                "%s is claimed in section 3 but absent from the matrix" % (row_id,),
            )
        )

    for row_id in sorted(ready_rows - certified_note_rows):
        issues.append(
            MatrixIssue(
                "release-notes-ready-row-missing",
                "%s is ready in the matrix but absent from section 3" % (row_id,),
            )
        )

    for row_id in sorted(certified_note_rows & set(row_statuses)):
        if row_statuses[row_id] in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue
        issues.append(
            MatrixIssue(
                "release-notes-uncertified-row-claimed",
                "%s is claimed in section 3 but matrix status is '%s'"
                % (row_id, row_statuses[row_id]),
            )
        )

    ready_evidence_paths = {
        evidence_path
        for _row_id, evidence_path in _claim_row_evidence_paths(matrix_text)
    }
    for evidence_path in sorted(ready_evidence_paths):
        if "`%s`" % (evidence_path,) in evidence_section:
            continue
        issues.append(
            MatrixIssue(
                "release-notes-evidence-missing",
                "%s is referenced by a ready matrix row but absent from section 2"
                % (evidence_path,),
            )
        )
    for evidence_path in sorted(set(EVIDENCE_RE.findall(evidence_section)) - ready_evidence_paths):
        issues.append(
            MatrixIssue(
                "release-notes-unclaimed-evidence-listed",
                "%s is listed in section 2 but not referenced by any ready matrix row"
                % (evidence_path,),
            )
        )

    nonclaim_note_rows = _row_ids_in_text(nonclaim_section)
    nonready_rows = set(row_statuses) - ready_rows
    for row_id in sorted(nonclaim_note_rows & ready_rows):
        issues.append(
            MatrixIssue(
                "release-notes-ready-row-nonclaimed",
                "%s is ready in the matrix but listed in section 4 as unclaimed"
                % (row_id,),
            )
        )
    for row_id in sorted(nonready_rows - nonclaim_note_rows):
        issues.append(
            MatrixIssue(
                "release-notes-nonclaim-row-missing",
                "%s is not ready in the matrix but absent from section 4" % (row_id,),
            )
        )
    issues.extend(_release_notes_subset_scope_issues(matrix_text, certification_section))
    issues.extend(_release_notes_module_nonclaim_issues(matrix_text, nonclaim_section))
    issues.extend(_release_notes_known_limitation_issues(matrix_text, limitations_section))

    for command in REQUIRED_M1_PRE_TAG_COMMANDS:
        if command in pre_tag_section:
            continue
        issues.append(
            MatrixIssue(
                "release-notes-pretag-command-missing",
                "section 7 is missing '%s'" % (command,),
            )
        )

    for detail in pretag_command_order_messages(pre_tag_section):
        issues.append(
            MatrixIssue(
                "release-notes-pretag-command-order",
                detail,
            )
        )
    for detail in pretag_command_duplicate_messages(pre_tag_section):
        issues.append(
            MatrixIssue(
                "release-notes-pretag-command-duplicate",
                detail,
            )
        )

    for row_id, suite_name in _ready_row_suite_refs(matrix_text):
        command = PRETAG_WRAPPER_COMMAND_BY_SUITE.get(suite_name)
        if command is None:
            issues.append(
                MatrixIssue(
                    "release-notes-ready-suite-wrapper-unknown",
                    "%s uses ready suite %s but no pre-tag wrapper command mapping exists"
                    % (row_id, suite_name),
                )
            )
            continue
        if command in pre_tag_section:
            continue
        issues.append(
            MatrixIssue(
                "release-notes-ready-suite-command-missing",
                "%s uses ready suite %s but section 7 is missing '%s'"
                % (row_id, suite_name, command),
            )
        )

    for row_id, suite_name in _nonready_row_suite_refs(matrix_text):
        command = PRETAG_WRAPPER_COMMAND_BY_SUITE.get(suite_name)
        if (
            command is None
            or command not in pre_tag_section
            or command in REQUIRED_M1_PRE_TAG_COMMANDS
        ):
            continue
        issues.append(
            MatrixIssue(
                "release-notes-nonready-suite-command-listed",
                "%s uses non-ready suite %s but section 7 lists '%s'"
                % (row_id, suite_name, command),
            )
        )

    return issues


def _release_notes_subset_scope_issues(
    matrix_text: str,
    certification_section: str,
) -> list[MatrixIssue]:
    """Validate release-note claims keep certified subset rows visibly scoped."""
    row_statuses = _claim_row_statuses(matrix_text)
    certification_claims = _release_notes_certification_claims(certification_section)
    issues = []
    for row_id, status_label in sorted(row_statuses.items()):
        if status_label not in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue
        parent_row_id = _subset_parent_row_id(row_id)
        if not parent_row_id or parent_row_id not in row_statuses:
            continue
        claim_text = certification_claims.get(row_id)
        if not claim_text:
            continue

        normalized_claim = _normalize_release_notes_text(claim_text)
        missing_markers = []
        if "software-only" not in normalized_claim and "software only" not in normalized_claim:
            missing_markers.append("software-only")
        if "subset" not in normalized_claim:
            missing_markers.append("subset")
        if row_id.endswith("-SW-LOCAL"):
            for marker in ("single-host", "cpu-capped"):
                marker_variant = marker.replace("-", " ")
                if marker not in normalized_claim and marker_variant not in normalized_claim:
                    missing_markers.append(marker)
        if not _row_id_mentioned(claim_text, parent_row_id):
            missing_markers.append(parent_row_id)
        if not missing_markers:
            continue

        issues.append(
            MatrixIssue(
                "release-notes-subset-scope-missing",
                "%s section 3 claim must state its scoped subset boundary; missing %s"
                % (row_id, ", ".join(missing_markers)),
            )
        )
    return issues


def _release_notes_certification_claims(certification_section: str) -> dict[str, str]:
    """Return release-note section-3 table claims keyed by matrix row ID."""
    claims = {}
    for line in certification_section.splitlines():
        if not line.startswith("|"):
            continue
        cells = _markdown_cells(line)
        if len(cells) < 2 or cells[0] in {"Row", "---"}:
            continue
        row_cell = cells[0]
        claim_text = " | ".join(cells[:2])
        for row_id in _row_ids_in_text(row_cell):
            claims[row_id] = claim_text
    return claims


RELEASE_NOTES_LIMITATION_REQUIREMENTS = (
    (
        "local-registry-cache",
        ("local registry cache", "registry cache"),
        ("local registry cache", "registry cache", "registry-cache"),
        "section 5 must mention the local registry cache blocker",
    ),
    (
        "host-helper-interface",
        ("hostctl_interface_version", "prime-registry-cache"),
        ("hostctl_interface_version", "prime-registry-cache"),
        "section 5 must mention the host-helper interface and cache-prime blocker",
    ),
    (
        "cloud-provider-evidence",
        ("cloud-backed evidence", "credential/cost", "credential docs"),
        ("cloud-backed evidence", "credential", "cost"),
        "section 5 must mention cloud evidence and credential/cost blockers",
    ),
    (
        "qemu-resource-capacity",
        ("exact 26-core", "external qemu capacity", "higher local core budget"),
        ("resource-shape", "external qemu", "larger/external qemu", "larger local"),
        "section 5 must mention the QEMU resource-shape/capacity blocker",
    ),
)


def _release_notes_known_limitation_issues(
    matrix_text: str,
    limitations_section: str,
) -> list[MatrixIssue]:
    """Validate release notes keep active matrix blockers in known limitations."""
    matrix_normalized = _normalize_release_notes_text(matrix_text)
    limitations_normalized = _normalize_release_notes_text(limitations_section)
    issues = []
    for requirement, source_markers, limitation_markers, detail in (
        RELEASE_NOTES_LIMITATION_REQUIREMENTS
    ):
        if not any(marker in matrix_normalized for marker in source_markers):
            continue
        if any(marker in limitations_normalized for marker in limitation_markers):
            continue
        issues.append(
            MatrixIssue(
                "release-notes-known-limitation-missing",
                "%s: %s" % (requirement, detail),
            )
        )
    return issues


def _release_notes_module_nonclaim_issues(
    matrix_text: str,
    nonclaim_section: str,
) -> list[MatrixIssue]:
    """Validate release notes list module-backlog items without ready evidence."""
    issues = []
    for module_cell, status_cell in _module_backlog_status_cells(matrix_text):
        status_label = _primary_status_label(status_cell)
        if (
            status_label not in ALLOWED_STATUS_LABELS
            or status_label in EVIDENCE_REQUIRED_STATUS_LABELS
        ):
            continue
        for module_name in _module_names_from_cell(module_cell):
            if _text_mentions_module(nonclaim_section, module_name):
                continue
            issues.append(
                MatrixIssue(
                    "release-notes-nonready-module-missing",
                    "%s module status is '%s' in the matrix but absent from section 4"
                    % (module_name, status_label),
                )
            )
    return issues


def _text_mentions_module(text: str, module_name: str) -> bool:
    lowered = text.lower().replace("`", "")
    for variant in _module_name_variants(module_name):
        pattern = r"(?<![a-z0-9_])%s(?![a-z0-9_])" % (re.escape(variant),)
        if re.search(pattern, lowered):
            return True
    return False


def _module_name_variants(module_name: str) -> set[str]:
    module_name = module_name.lower()
    variants = {
        module_name,
        module_name.replace("_", "-"),
        module_name.replace("_", " "),
    }
    if module_name == "baremetal":
        variants.update({"bare-metal", "bare metal"})
    return variants


def _normalize_release_notes_text(text: str) -> str:
    """Normalize release-note prose for wording-gate checks."""
    return " ".join(text.lower().replace("`", "").split())


def _states_intermediate_release(text: str) -> bool:
    return (
        "intermediate" in text
        and any(marker in text for marker in ("milestone", "pre-release", "release"))
    ) or "pre-release" in text


def _states_not_final_replacement(text: str) -> bool:
    if "not" not in text or "main" not in text:
        return False
    return (
        "not a final replacement" in text
        or "not final replacement" in text
        or "not a full replacement" in text
        or "not full replacement" in text
    )


def _nonready_row_suite_refs(text: str) -> Iterable[tuple[str, str]]:
    """Yield non-ready matrix row IDs and their referenced test suites."""
    for cells in _claim_table_rows(text):
        if len(cells) < 5:
            continue
        status_label = _primary_status_label(cells[4])
        if (
            status_label not in ALLOWED_STATUS_LABELS
            or status_label in EVIDENCE_REQUIRED_STATUS_LABELS
        ):
            continue
        row_id = cells[0]
        row_text = " | ".join(cells)
        for suite_name in sorted(set(SUITE_REF_RE.findall(row_text))):
            yield row_id, suite_name


def _parity_backlog_issues(root: Path, matrix_text: str) -> list[MatrixIssue]:
    """Return drift issues between non-ready matrix rows and the issue seed."""
    backlog_path = root / PARITY_BACKLOG_PATH
    if not backlog_path.exists():
        return [MatrixIssue("parity-backlog-missing", PARITY_BACKLOG_PATH.as_posix())]

    backlog_text = backlog_path.read_text(encoding="utf-8")
    row_statuses = {
        row_id: status_label
        for row_id, status_label in _claim_row_statuses(matrix_text).items()
        if row_id.startswith("P-") and status_label in ALLOWED_STATUS_LABELS
    }
    row_actions = {
        row_id: action
        for row_id, _status, action in _claim_rows(matrix_text)
        if row_id.startswith("P-")
    }
    nonready_rows = {
        row_id
        for row_id, status_label in row_statuses.items()
        if status_label not in EVIDENCE_REQUIRED_STATUS_LABELS
    }
    backlog_rows = {}

    issues = []
    issues.extend(_parity_backlog_conversion_note_issues(backlog_text))
    for row_id, status_cell, issue_seed, action_snapshot in _parity_backlog_rows(backlog_text):
        status_label = _primary_status_label(status_cell)
        if row_id in backlog_rows:
            issues.append(MatrixIssue("parity-backlog-duplicate-row", row_id))
            continue
        if not status_label:
            issues.append(MatrixIssue("parity-backlog-missing-status", row_id))
        elif status_label not in ALLOWED_STATUS_LABELS:
            issues.append(
                MatrixIssue(
                    "parity-backlog-invalid-status",
                    "%s uses unknown status '%s'" % (row_id, status_label),
                )
            )
        backlog_rows[row_id] = (status_label, issue_seed, action_snapshot)

    backlog_row_ids = set(backlog_rows)
    for row_id in sorted(backlog_row_ids - set(row_statuses)):
        issues.append(
            MatrixIssue(
                "parity-backlog-unknown-row",
                "%s is listed in %s but absent from the matrix"
                % (row_id, PARITY_BACKLOG_PATH.as_posix()),
            )
        )

    for row_id in sorted(nonready_rows - backlog_row_ids):
        issues.append(
            MatrixIssue(
                "parity-backlog-nonready-row-missing",
                "%s is not ready in the matrix but absent from %s"
                % (row_id, PARITY_BACKLOG_PATH.as_posix()),
            )
        )

    for row_id in sorted((backlog_row_ids & set(row_statuses)) - nonready_rows):
        issues.append(
            MatrixIssue(
                "parity-backlog-ready-row-listed",
                "%s is ready in the matrix but still listed as future work in %s"
                % (row_id, PARITY_BACKLOG_PATH.as_posix()),
            )
        )

    for row_id in sorted(nonready_rows & backlog_row_ids):
        backlog_status, issue_seed, action_snapshot = backlog_rows[row_id]
        matrix_status = row_statuses[row_id]
        if backlog_status and backlog_status in ALLOWED_STATUS_LABELS:
            if backlog_status != matrix_status:
                issues.append(
                    MatrixIssue(
                        "parity-backlog-status-mismatch",
                        "%s backlog status '%s' does not match matrix status '%s'"
                        % (row_id, backlog_status, matrix_status),
                    )
                )
        if not issue_seed.strip():
            issues.append(
                MatrixIssue(
                    "parity-backlog-empty-issue-seed",
                    "%s has no actionable issue seed in %s"
                    % (row_id, PARITY_BACKLOG_PATH.as_posix()),
                )
            )
        elif not _has_evidence_or_disposition_closure_path(issue_seed):
            issues.append(
                MatrixIssue(
                    "parity-backlog-closure-path-missing",
                    "%s issue seed must require fresh evidence or an explicit "
                    "historical/deprecation disposition" % (row_id,),
                )
            )
        matrix_action = row_actions.get(row_id, "")
        if not action_snapshot.strip():
            issues.append(
                MatrixIssue(
                    "parity-backlog-action-snapshot-missing",
                    "%s must copy the matrix Certification Action into %s"
                    % (row_id, PARITY_BACKLOG_PATH.as_posix()),
                )
            )
        elif _normalize_backlog_text(action_snapshot) != _normalize_backlog_text(matrix_action):
            issues.append(
                MatrixIssue(
                    "parity-backlog-action-snapshot-mismatch",
                    "%s action snapshot does not match matrix Certification Action"
                    % (row_id,),
                )
            )
    return issues


def _parity_backlog_conversion_note_issues(text: str) -> list[MatrixIssue]:
    """Validate issue-conversion notes keep release evidence discipline."""
    normalized = _normalize_release_notes_text(text)
    issues = []
    for marker_id, markers, detail in REQUIRED_PARITY_BACKLOG_CONVERSION_MARKERS:
        if all(marker in normalized for marker in markers):
            continue
        issues.append(
            MatrixIssue(
                "parity-backlog-conversion-note-missing",
                "%s: %s" % (marker_id, detail),
            )
        )
    return issues


def _normalize_backlog_text(text: str) -> str:
    """Normalize markdown-table prose for exact row-action drift checks."""
    return " ".join(text.strip().split())


def _has_evidence_or_disposition_closure_path(text: str) -> bool:
    """Return whether text states an evidence path or final disposition path."""
    lowered = text.lower()
    evidence_path = "evidence" in lowered and any(
        marker in lowered for marker in ("certif", "record", "run")
    )
    disposition_path = any(
        marker in lowered for marker in ("deprecat", "demote", "historical", "remove")
    )
    return evidence_path or disposition_path


def _parity_backlog_rows(text: str) -> Iterable[tuple[str, str, str, str]]:
    """Yield row ID, status, issue seed, and matrix-action snapshot cells."""
    for line in text.splitlines():
        if not line.startswith("| `P-") and not line.startswith("| P-"):
            continue
        cells = _markdown_cells(line)
        row_id = _row_id_from_cell(cells[0] if cells else "<unknown>")
        status_cell = cells[1] if len(cells) >= 2 else ""
        issue_seed = cells[2] if len(cells) >= 3 else ""
        action_snapshot = cells[3] if len(cells) >= 4 else ""
        yield row_id, status_cell, issue_seed, action_snapshot


def _claim_evidence_issues(root: Path, text: str) -> list[MatrixIssue]:
    issues = []
    for row_id, status, action in _claim_rows(text):
        status_label = _primary_status_label(status)
        if status_label not in EVIDENCE_REQUIRED_STATUS_LABELS:
            continue

        evidence_paths = EVIDENCE_RE.findall(action)
        if not evidence_paths:
            issues.append(
                MatrixIssue(
                    "claim-row-missing-evidence",
                    "%s has no evidence doc" % (row_id,),
                )
            )
            continue
        evidence_texts = []
        for evidence_path in evidence_paths:
            evidence_file = root / evidence_path
            if not evidence_file.exists():
                issues.append(
                    MatrixIssue(
                        "claim-row-evidence-missing",
                        "%s references missing %s" % (row_id, evidence_path),
                    )
                )
                continue
            evidence_texts.append(evidence_file.read_text(encoding="utf-8"))
        if evidence_texts and not any(
            _row_id_mentioned(evidence_text, row_id) for evidence_text in evidence_texts
        ):
            issues.append(
                MatrixIssue(
                    "claim-row-evidence-row-missing",
                    "%s is not named in its evidence doc(s)" % (row_id,),
                )
            )
    return issues


def _row_id_mentioned(text: str, row_id: str) -> bool:
    """Return whether text mentions a matrix row ID without prefix ambiguity."""
    pattern = r"(?<![A-Z0-9-])%s(?![A-Z0-9-])" % (re.escape(row_id),)
    return re.search(pattern, text) is not None


def _m1_core_gate_issues(text: str) -> list[MatrixIssue]:
    """Validate that the M1-CORE row names the required cloud audit gates."""
    for line in text.splitlines():
        if not line.startswith("| M1-CORE "):
            continue
        return [
            MatrixIssue(
                "m1-core-required-gate-missing",
                "M1-CORE required evidence does not name %s" % (gate,),
            )
            for gate in REQUIRED_CLOUD_AUDIT_GATES
            if gate not in line
        ]
    return []


def _preferred_host_sequence_issues(text: str) -> list[MatrixIssue]:
    """Validate numbering in the matrix's preferred host command sequence."""
    lines = text.splitlines()
    try:
        start_index = lines.index("Preferred M1 host command sequence:") + 1
    except ValueError:
        return []

    sequence_items: list[tuple[int, str]] = []
    for line in lines[start_index:]:
        if not line.strip():
            if sequence_items:
                break
            continue
        match = NUMBERED_COMMAND_RE.match(line)
        if not match:
            if sequence_items:
                break
            continue
        sequence_items.append((int(match.group(1)), match.group(2)))

    issues = []
    listed_commands = {command for _number, command in sequence_items}
    for expected_number, (actual_number, command) in enumerate(sequence_items, start=1):
        if actual_number == expected_number:
            continue
        issues.append(
            MatrixIssue(
                "matrix-host-command-numbering",
                "Preferred M1 host command sequence lists %r as item %d; expected item %d"
                % (command, actual_number, expected_number),
            )
        )

    if not sequence_items:
        return issues

    for command in REQUIRED_M1_HOST_SEQUENCE_COMMANDS:
        if command in listed_commands:
            continue
        issues.append(
            MatrixIssue(
                "matrix-host-required-command-missing",
                "Preferred M1 host command sequence is missing '%s'" % (command,),
            )
        )

    for row_id, suite_name in _ready_row_suite_refs(text):
        command = PRETAG_WRAPPER_COMMAND_BY_SUITE.get(suite_name)
        if command is None or command in listed_commands:
            continue
        issues.append(
            MatrixIssue(
                "matrix-host-ready-suite-command-missing",
                "%s uses ready suite %s but Preferred M1 host command sequence "
                "is missing '%s'" % (row_id, suite_name, command),
            )
        )
    return issues


def find_matrix_issues(root: Path = ROOT) -> list[MatrixIssue]:
    """Return release-matrix drift issues."""
    root = root.resolve()
    text = _matrix_text(root)
    issues: list[MatrixIssue] = []

    if _is_git_work_tree(root) and not _old_main_ref_available(root):
        issues.append(
            MatrixIssue(
                "old-main-ref-unavailable",
                "local git ref %s is required for old-main parity inventory checks"
                % (OLD_MAIN_REF,),
            )
        )

    legacy_configs = sorted(
        set(iter_legacy_test_configs(root)) | set(iter_old_main_legacy_test_configs(root))
    )
    for legacy_config in legacy_configs:
        if legacy_config not in text:
            issues.append(MatrixIssue("legacy-config-missing", legacy_config))

    for parity_config in iter_parity_yaml(root):
        if parity_config not in text:
            issues.append(MatrixIssue("parity-yaml-unreferenced", parity_config))

    for suite_name in iter_parity_suites(root):
        if "`%s`" % (suite_name,) not in text:
            issues.append(MatrixIssue("parity-suite-unreferenced", suite_name))

    issues.extend(_status_label_issues(text))
    issues.extend(_module_backlog_certified_row_issues(text))
    issues.extend(_claim_action_closure_issues(text))
    issues.extend(_subset_row_scope_issues(text))
    issues.extend(_m1_core_gate_issues(text))
    issues.extend(_preferred_host_sequence_issues(text))
    issues.extend(_evidence_template_issues(text))
    issues.extend(_planning_stack_issues(root))
    issues.extend(_certified_row_scope_issues(text))
    issues.extend(_claim_reference_issues(root, text))
    issues.extend(_claim_evidence_issues(root, text))
    issues.extend(_release_notes_issues(root, text))
    issues.extend(_parity_backlog_issues(root, text))
    return issues


def main() -> int:
    """Run the release-matrix drift check."""
    issues = find_matrix_issues(ROOT)
    for issue in issues:
        print("%s: %s" % (issue.kind, issue.detail))
    print("TOTAL_RELEASE_MATRIX_ISSUES=%d" % (len(issues)))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
