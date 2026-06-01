#!/usr/bin/env python3
"""Check whether the documented M1 pre-tag evidence is release-ready."""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from pathlib import Path

try:
    from scripts.test.check_release_evidence_artifacts import check_cloud_static_audit_report
    from scripts.test.check_release_matrix import (
        REQUIRED_M1_PRE_TAG_COMMANDS,
        pretag_command_duplicate_messages,
        pretag_command_order_messages,
        section_text,
    )
except ModuleNotFoundError:  # pragma: no cover - used when run as a script path
    from check_release_evidence_artifacts import check_cloud_static_audit_report
    from check_release_matrix import (
        REQUIRED_M1_PRE_TAG_COMMANDS,
        pretag_command_duplicate_messages,
        pretag_command_order_messages,
        section_text,
    )


ROOT = Path(__file__).resolve().parents[2]
RELEASE_NOTES_PATH = Path("docs/release_notes_m1_draft.md")
M1_EVIDENCE_PATH = Path("docs/release_evidence_m1_2026-06-01.md")
RELEASE_EVIDENCE_DOC_RE = re.compile(r"`(docs/release_evidence_[^`]+\.md)`")
CLOUD_AUDIT_REPORT_NAME_RE = re.compile(
    r"^cloud_static_audit_(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{6}Z)\.md$"
)
CLOUD_AUDIT_HEADING_RE = re.compile(
    r"^# Cloud Static Audit Report - (?P<timestamp>\d{4}-\d{2}-\d{2}T\d{6}Z)$",
    re.MULTILINE,
)
REQUIRED_PRETAG_COMMANDS = REQUIRED_M1_PRE_TAG_COMMANDS
EXPECTED_M1_EVIDENCE_FIELDS = {
    "Required gates": "PASS",
    "Result": "TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0",
    "Verify command": "sudo -n /usr/local/bin/continuum-hostctl verify",
    "Verify result": "PASS",
}
POST_EVIDENCE_ALLOWED_PATH_PREFIXES = (
    ".codex/skills/",
    "docs/",
    "scripts/test/check_release_",
    "scripts/test/run_cloud_static_audit.sh",
    "scripts/test/e2e/test_",
    "scripts/test/unit/test_check_release_",
)
RELEASE_ARTIFACT_AUDIT_WRAPPER_PATHS = {
    "scripts/test/run_smoke_host.sh",
    "scripts/test/setup_agent_host.sh",
}
RELEASE_ARTIFACT_AUDIT_ADDED_LINES = {
    '  release-artifact-audit)',
    '    BASE_PATH="$BASE_ROOT/prereqs"',
    '    CONTINUUM_HOME="$BASE_PATH/.continuum"',
    '    MPLCONFIGDIR_PATH="$CONTINUUM_HOME/mplconfig"',
    '    XDG_CACHE_HOME_PATH="$BASE_ROOT/.cache"',
    '    mkdir -p "$BASE_PATH" "$CONTINUUM_HOME" "$MPLCONFIGDIR_PATH" "$XDG_CACHE_HOME_PATH"',
    '    chmod 0750 "$BASE_PATH" "$CONTINUUM_HOME" "$MPLCONFIGDIR_PATH" "$XDG_CACHE_HOME_PATH"',
    '    cd "$REPO_ROOT"',
    '    exec env -i \\',
    '      HOME="${HOME:-/home/continuum-smoke}" \\',
    '      PATH="$VENV_BIN:$SAFE_PATH" \\',
    '      PYTHONPATH=. \\',
    '      PYTHONDONTWRITEBYTECODE=1 \\',
    '      XDG_CACHE_HOME="$XDG_CACHE_HOME_PATH" \\',
    '      MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \\',
    '      CONTINUUM_RELEASE_AUDIT_ROOT="${CONTINUUM_RELEASE_AUDIT_ROOT:-$REPO_ROOT}" \\',
    '      CONTINUUM_SMOKE_BASE_ROOT="$BASE_ROOT" \\',
    '      CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \\',
    '      LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \\',
    '      "$PYTHON_BIN" scripts/test/check_release_evidence_artifacts.py',
    "    ;;",
    'HOSTCTL_INTERFACE_VERSION="2026-06-01-release-artifact-audit-root"',
    '  CONTINUUM_RELEASE_AUDIT_ROOT="$LIVE_REPO_ROOT" \\\\',
    '  CONTINUUM_RELEASE_AUDIT_ROOT="\\$LIVE_REPO_ROOT" \\\\',
}
RELEASE_ARTIFACT_AUDIT_REMOVED_LINES = {
    'HOSTCTL_INTERFACE_VERSION="2026-05-31-sudo-hardening"',
}
STALE_HOST_HELPER_FINDING_RE = re.compile(
    r"\b("
    r"does not declare|does not expose|fail(?:ed|ure)?|missing|not ready|stale|"
    r"refresh the root-owned helper"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PretagIssue:
    """A pre-tag readiness issue."""

    kind: str
    detail: str


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_field_value(value: str) -> str:
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        return value[1:-1]
    return value


def _table_fields(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = _markdown_cells(line)
        if len(cells) < 2:
            continue
        if cells[0] in ("Field", "---"):
            continue
        fields[cells[0]] = _normalize_field_value(cells[1])
    return fields


def _extract_paths(text: str) -> list[str]:
    return re.findall(r"(?:^|[\s`])(/[^`\s]+)", text, flags=re.MULTILINE)


def _cloud_audit_report_dir(root: Path) -> Path:
    return (root / "logs" / "cloud_static_audit").resolve()


def _cloud_audit_report_timestamp_issues(report_path: Path) -> list[PretagIssue]:
    """Return issues when the report filename and heading timestamps disagree."""
    name_match = CLOUD_AUDIT_REPORT_NAME_RE.match(report_path.name)
    if name_match is None:
        return []

    try:
        report_text = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            PretagIssue(
                "pretag-cloud-audit-report-unreadable",
                "%s could not be read: %s" % (report_path, exc),
            )
        ]

    heading_match = CLOUD_AUDIT_HEADING_RE.search(report_text)
    if heading_match is None:
        return [
            PretagIssue(
                "pretag-cloud-audit-report-heading-missing",
                "%s missing '# Cloud Static Audit Report - <timestamp>' heading"
                % (report_path,),
            )
        ]

    filename_timestamp = name_match.group("timestamp")
    heading_timestamp = heading_match.group("timestamp")
    if filename_timestamp == heading_timestamp:
        return []
    return [
        PretagIssue(
            "pretag-cloud-audit-report-timestamp-mismatch",
            "%s filename timestamp %s does not match heading timestamp %s"
            % (report_path, filename_timestamp, heading_timestamp),
        )
    ]


def _git_output(root: Path, args: list[str]) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _current_git_commit(root: Path) -> str | None:
    return _git_output(root, ["rev-parse", "HEAD"])


def _git_status_porcelain(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def _git_diff_check(root: Path) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--check"],
        capture_output=True,
        check=False,
        text=True,
    )
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return result.returncode, output


def _changed_paths_between_commits(
    root: Path, base_commit: str, current_commit: str
) -> list[str] | None:
    """Return paths changed between the VM-evidence source and current HEAD."""
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", base_commit, current_commit],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _diff_lines_between_commits(
    root: Path,
    base_commit: str,
    current_commit: str,
    paths: list[str],
) -> list[str] | None:
    """Return zero-context diff lines for selected paths."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--unified=0",
            base_commit,
            current_commit,
            "--",
            *paths,
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def _is_allowed_post_evidence_path(path: str) -> bool:
    """Return whether a path may change after VM evidence without rerunning VMs."""
    normalized = path.replace("\\", "/")
    return any(
        normalized.startswith(prefix) for prefix in POST_EVIDENCE_ALLOWED_PATH_PREFIXES
    )


def _is_allowed_release_artifact_audit_diff_line(line: str) -> bool:
    """Return whether one diff line belongs to the wrapper-only audit addition."""
    if not line or line.startswith(("diff ", "index ", "@@", "+++", "---")):
        return True
    if line.startswith("+"):
        content = line[1:]
        return (
            content in RELEASE_ARTIFACT_AUDIT_ADDED_LINES
            or (
                content.startswith('    echo "Allowed values:')
                and "release-artifact-audit" in content
            )
        )
    if line.startswith("-"):
        content = line[1:]
        return (
            content in RELEASE_ARTIFACT_AUDIT_REMOVED_LINES
            or (
                content.startswith('    echo "Allowed values:')
                and "release-artifact-audit" not in content
            )
        )
    return True


def _is_release_artifact_audit_only_wrapper_change(
    root: Path,
    evidence_commit: str,
    current_commit: str,
    disallowed_paths: list[str],
) -> bool:
    """Return whether disallowed paths are exactly the guarded audit wrapper delta."""
    normalized_paths = {path.replace("\\", "/") for path in disallowed_paths}
    if normalized_paths != RELEASE_ARTIFACT_AUDIT_WRAPPER_PATHS:
        return False
    diff_lines = _diff_lines_between_commits(
        root,
        evidence_commit,
        current_commit,
        sorted(RELEASE_ARTIFACT_AUDIT_WRAPPER_PATHS),
    )
    if diff_lines is None:
        return False
    return all(_is_allowed_release_artifact_audit_diff_line(line) for line in diff_lines)


def _source_commit_mismatch_issue(
    root: Path,
    evidence_doc: str,
    evidence_commit: str,
    current_commit: str,
) -> PretagIssue | None:
    """Return a source-commit issue unless only release guardrails changed."""
    changed_paths = _changed_paths_between_commits(root, evidence_commit, current_commit)
    if changed_paths is None:
        return PretagIssue(
            "pretag-source-commit-mismatch",
            "%s Git commit=%r expected current HEAD %r"
            % (evidence_doc, evidence_commit, current_commit),
        )

    disallowed_paths = [
        path for path in changed_paths if not _is_allowed_post_evidence_path(path)
    ]
    if not disallowed_paths:
        return None
    if _is_release_artifact_audit_only_wrapper_change(
        root,
        evidence_commit,
        current_commit,
        disallowed_paths,
    ):
        return None

    sample_paths = ", ".join(disallowed_paths[:5])
    return PretagIssue(
        "pretag-source-commit-mismatch",
        "%s Git commit=%r differs from current HEAD %r; runtime-affecting "
        "paths changed since evidence commit: %s"
        % (evidence_doc, evidence_commit, current_commit, sample_paths),
    )


def _git_status_category(line: str) -> str:
    """Return a stable category for one git porcelain status line."""
    status = line[:2] if len(line) >= 2 else line
    category = "changed"
    if status == "??":
        category = "untracked"
    elif status == "!!":
        category = "ignored"
    elif "U" in status or status in ("AA", "DD"):
        category = "unmerged"
    elif "R" in status:
        category = "renamed"
    elif "C" in status:
        category = "copied"
    elif "A" in status:
        category = "added"
    elif "D" in status:
        category = "deleted"
    elif "M" in status:
        category = "modified"
    return category


def _git_status_path(line: str) -> str:
    if len(line) >= 4:
        return line[3:].strip()
    return line.strip()


def _git_status_category_summary(categories: dict[str, int]) -> str:
    preferred_order = (
        "unmerged",
        "modified",
        "added",
        "deleted",
        "renamed",
        "copied",
        "untracked",
        "ignored",
        "changed",
    )
    ordered_categories = [
        category for category in preferred_order if category in categories
    ]
    ordered_categories.extend(sorted(set(categories) - set(preferred_order)))
    return ", ".join(
        "%s=%d" % (category, categories[category]) for category in ordered_categories
    )


def _git_status_dirty_detail(status_text: str, path_limit: int = 5) -> str:
    """Return a concise dirty-worktree detail suitable for release reports."""
    lines = [line for line in status_text.splitlines() if line.strip()]
    categories: dict[str, int] = {}
    sample_paths: list[str] = []

    for line in lines:
        category = _git_status_category(line)
        categories[category] = categories.get(category, 0) + 1
        if len(sample_paths) < path_limit:
            sample_paths.append(_git_status_path(line))

    detail = "git status --porcelain reports %d changed paths" % (len(lines),)
    category_summary = _git_status_category_summary(categories)
    if category_summary:
        detail += " (%s)" % (category_summary,)
    if sample_paths:
        detail += "; sample paths: %s" % (", ".join(sample_paths),)
    return detail + "; release tag requires a clean worktree"


def _is_clean_tree_state(tree_state: str) -> bool:
    lowered = tree_state.strip().lower()
    return lowered.startswith("clean") and "dirty" not in lowered


def _release_note_evidence_docs(root: Path) -> list[str]:
    notes_path = root / RELEASE_NOTES_PATH
    if not notes_path.exists():
        return []
    notes_text = notes_path.read_text(encoding="utf-8")
    evidence_section = section_text(notes_text, "## 2. Primary Evidence")
    return sorted(set(RELEASE_EVIDENCE_DOC_RE.findall(evidence_section)))


def _release_notes_issues(root: Path) -> list[PretagIssue]:
    notes_path = root / RELEASE_NOTES_PATH
    if not notes_path.exists():
        return [PretagIssue("pretag-release-notes-missing", RELEASE_NOTES_PATH.as_posix())]

    notes_text = notes_path.read_text(encoding="utf-8")
    pretag_section = section_text(notes_text, "## 7. Pre-Tag Gate")
    issues = []
    for command in REQUIRED_PRETAG_COMMANDS:
        if command in pretag_section:
            continue
        issues.append(
            PretagIssue(
                "pretag-command-missing",
                "section 7 is missing '%s'" % (command,),
            )
        )

    for detail in pretag_command_order_messages(pretag_section, REQUIRED_PRETAG_COMMANDS):
        issues.append(
            PretagIssue(
                "pretag-command-order",
                detail,
            )
        )
    for detail in pretag_command_duplicate_messages(pretag_section, REQUIRED_PRETAG_COMMANDS):
        issues.append(
            PretagIssue(
                "pretag-command-duplicate",
                detail,
            )
        )
    return issues


def _m1_evidence_doc_issues(root: Path) -> list[PretagIssue]:
    evidence_path = root / M1_EVIDENCE_PATH
    if not evidence_path.exists():
        return [PretagIssue("pretag-evidence-missing", M1_EVIDENCE_PATH.as_posix())]

    evidence_text = evidence_path.read_text(encoding="utf-8")
    fields = _table_fields(evidence_text)
    issues = []
    for field, expected in EXPECTED_M1_EVIDENCE_FIELDS.items():
        actual = fields.get(field)
        if actual == expected:
            continue
        if actual is None:
            issues.append(
                PretagIssue(
                    "pretag-evidence-field-missing",
                    "%s missing %s" % (M1_EVIDENCE_PATH.as_posix(), field),
                )
            )
            continue
        issue_kind = "pretag-evidence-field-mismatch"
        if field == "Verify command":
            issue_kind = "pretag-host-helper-command-mismatch"
        if field == "Verify result":
            issue_kind = "pretag-host-helper-not-ready"
        issues.append(
            PretagIssue(
                issue_kind,
                "%s %s=%r expected %r" % (
                    M1_EVIDENCE_PATH.as_posix(),
                    field,
                    actual,
                    expected,
                ),
            )
        )

    if not fields.get("Report"):
        issues.append(
            PretagIssue(
                "pretag-evidence-field-missing",
                "%s missing Report" % (M1_EVIDENCE_PATH.as_posix(),),
            )
        )

    if fields.get("Verify result") == "PASS":
        current_finding = fields.get("Current finding", "")
        if STALE_HOST_HELPER_FINDING_RE.search(current_finding):
            issues.append(
                PretagIssue(
                    "pretag-host-helper-finding-not-cleared",
                    "%s Current finding=%r must be cleared when Verify result is PASS"
                    % (M1_EVIDENCE_PATH.as_posix(), current_finding),
                )
            )
    elif "after the helper-contract refresh" in evidence_text:
        issues.append(
            PretagIssue(
                "pretag-host-helper-refresh-wording-stale",
                "%s says 'after the helper-contract refresh' but Verify result is %r"
                % (M1_EVIDENCE_PATH.as_posix(), fields.get("Verify result")),
            )
        )

    missing_report_paths: set[Path] = set()
    report_value = fields.get("Report")
    if report_value:
        report_path = Path(report_value)
        if not report_path.is_absolute():
            report_path = root / report_path
        expected_report_dir = _cloud_audit_report_dir(root)
        if report_path.resolve().parent != expected_report_dir:
            issues.append(
                PretagIssue(
                    "pretag-cloud-audit-report-location",
                    "%s Report=%r must be under %r"
                    % (
                        M1_EVIDENCE_PATH.as_posix(),
                        str(report_path),
                        str(expected_report_dir),
                    ),
                )
            )
        if not CLOUD_AUDIT_REPORT_NAME_RE.match(report_path.name):
            issues.append(
                PretagIssue(
                    "pretag-cloud-audit-report-name",
                    "%s Report=%r must use cloud_static_audit_YYYY-MM-DDTHHMMSSZ.md"
                    % (M1_EVIDENCE_PATH.as_posix(), str(report_path)),
                )
            )
        if not report_path.exists():
            missing_report_paths.add(report_path.resolve())
            issues.append(
                PretagIssue(
                    "pretag-evidence-artifact-missing",
                    "%s references missing %s"
                    % (M1_EVIDENCE_PATH.as_posix(), report_path),
                )
            )
        else:
            issues.extend(_cloud_audit_report_timestamp_issues(report_path))
            for report_issue in check_cloud_static_audit_report(
                report_path,
                M1_EVIDENCE_PATH.as_posix(),
                evidence_path,
            ):
                issues.append(
                    PretagIssue(
                        "pretag-cloud-audit-evidence-invalid",
                        "%s: %s" % (report_issue.kind, report_issue.detail),
                    )
                )
            issues.extend(_cloud_audit_report_latest_issues(root, report_path))

    for absolute_path in _extract_paths(evidence_text):
        path = Path(absolute_path)
        if not any(suffix in path.name for suffix in ("cloud_static_audit_", "test_results_")):
            continue
        if path.resolve() in missing_report_paths:
            continue
        if path.exists():
            continue
        issues.append(
            PretagIssue(
                "pretag-evidence-artifact-missing",
                "%s references missing %s" % (M1_EVIDENCE_PATH.as_posix(), path),
            )
        )
    return issues


def _cloud_audit_report_latest_issues(root: Path, report_path: Path) -> list[PretagIssue]:
    """Return a pre-tag issue when M1 evidence points at an older audit report."""
    report_dir = _cloud_audit_report_dir(root)
    report_path = report_path.resolve()
    if report_path.parent != report_dir or not report_dir.is_dir():
        return []

    reports = sorted(report_dir.glob("cloud_static_audit_*.md"), key=lambda path: path.name)
    if not reports:
        return []

    latest_report = reports[-1].resolve()
    if report_path == latest_report:
        return []
    return [
        PretagIssue(
            "pretag-cloud-audit-report-not-latest",
            "%s Report=%r but latest cloud audit report is %r"
            % (M1_EVIDENCE_PATH.as_posix(), str(report_path), str(latest_report)),
        )
    ]


def _evidence_source_issues(root: Path) -> list[PretagIssue]:
    evidence_docs = sorted(
        set(_release_note_evidence_docs(root)) | {M1_EVIDENCE_PATH.as_posix()}
    )
    issues: list[PretagIssue] = []
    current_commit = _current_git_commit(root)
    status_text = _git_status_porcelain(root)

    if current_commit is None:
        issues.append(
            PretagIssue(
                "pretag-source-git-unavailable",
                "could not resolve current git commit",
            )
        )
    if status_text is None:
        issues.append(
            PretagIssue(
                "pretag-source-status-unavailable",
                "could not inspect current git status",
            )
        )
    elif status_text.strip():
        issues.append(
            PretagIssue(
                "pretag-source-tree-dirty",
                _git_status_dirty_detail(status_text),
            )
        )

    diff_status, diff_output = _git_diff_check(root)
    if diff_status != 0:
        first_line = next(
            (line.strip() for line in diff_output.splitlines() if line.strip()),
            "git diff --check exited with status %s" % (diff_status,),
        )
        issues.append(
            PretagIssue(
                "pretag-diff-check-failed",
                "git diff --check failed: %s" % (first_line,),
            )
        )

    for evidence_doc in evidence_docs:
        evidence_path = root / evidence_doc
        if not evidence_path.exists():
            if evidence_doc != M1_EVIDENCE_PATH.as_posix():
                issues.append(PretagIssue("pretag-evidence-missing", evidence_doc))
            continue
        fields = _table_fields(evidence_path.read_text(encoding="utf-8"))
        evidence_commit = fields.get("Git commit")
        if not evidence_commit:
            issues.append(
                PretagIssue(
                    "pretag-evidence-field-missing",
                    "%s missing Git commit" % (evidence_doc,),
                )
            )
        elif current_commit is not None and evidence_commit != current_commit:
            issue = _source_commit_mismatch_issue(
                root,
                evidence_doc,
                evidence_commit,
                current_commit,
            )
            if issue is not None:
                issues.append(issue)

        tree_state = fields.get("Tree state")
        if not tree_state:
            issues.append(
                PretagIssue(
                    "pretag-evidence-field-missing",
                    "%s missing Tree state" % (evidence_doc,),
                )
            )
        elif not _is_clean_tree_state(tree_state):
            issues.append(
                PretagIssue(
                    "pretag-evidence-tree-not-clean",
                    "%s Tree state=%r; release-tag evidence must come from a "
                    "clean source tree" % (evidence_doc, tree_state),
                )
            )
    return issues


def find_pretag_issues(root: Path = ROOT) -> list[PretagIssue]:
    """Return M1 pre-tag readiness issues from committed evidence docs."""
    root = root.resolve()
    issues = []
    issues.extend(_release_notes_issues(root))
    issues.extend(_m1_evidence_doc_issues(root))
    issues.extend(_evidence_source_issues(root))
    return issues


def main() -> int:
    """Run the M1 pre-tag readiness check."""
    issues = find_pretag_issues(ROOT)
    for issue in issues:
        print("%s: %s" % (issue.kind, issue.detail))
    print("TOTAL_RELEASE_PRETAG_ISSUES=%d" % (len(issues)))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
