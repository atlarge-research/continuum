#!/usr/bin/env python3
"""Check public release-facing docs for unsupported support claims."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = Path("docs/release_certification_matrix.md")
RELEASE_NOTES_PATH = Path("docs/release_notes_m1_draft.md")
PUBLIC_RELEASE_DOCS = (
    Path("README.md"),
    Path("docs/configuration_reference.md"),
    Path("docs/migration_notes.md"),
    Path("docs/cheatsheet.md"),
    Path("docs/operational_testing_strategy.md"),
    Path("docs/smoke_runner_isolation.md"),
    Path("docs/phase_d_handoff.md"),
    Path("docs/rework_plan_stack.md"),
    Path("docs/rework_kickoff.md"),
    Path("docs/rework_milestone_release_plan.md"),
    Path("docs/old_main_parity_issue_seed.md"),
    Path("docs/post_release_roadmap.md"),
    RELEASE_NOTES_PATH,
    Path("configuration/README.md"),
)
SCANNED_RELEASE_DOCS = (MATRIX_PATH, *PUBLIC_RELEASE_DOCS)
MATRIX_REFERENCE_REQUIRED_DOCS = PUBLIC_RELEASE_DOCS
ADDITIONAL_CLAIM_SCAN_GLOBS = (
    "docs/*.md",
    "configuration/**/*.md",
)
INLINE_CODE_RE = re.compile(r"`[^`]*`")


@dataclass(frozen=True)
class ReleaseClaimIssue:
    """A release-claim hygiene issue."""

    kind: str
    detail: str


@dataclass(frozen=True)
class ClaimPattern:
    """A line-level unsupported claim pattern."""

    kind: str
    regex: re.Pattern[str]
    detail: str


CLAIM_PATTERNS = (
    ClaimPattern(
        "qemu-core-claim",
        re.compile(
            r"\bqemu\s+core\b|"
            r"\bcore\s+qemu\b|"
            r"\bqemu\b.{0,80}\b(?:as|inside|part\s+of)\b.{0,80}"
            r"\b(?:continuum\s+)?core\b|"
            r"\b(?:continuum\s+)?core\b.{0,80}\b(?:includes|contains)\b.{0,80}"
            r"\bqemu\b",
            re.IGNORECASE,
        ),
        "describe QEMU as a provider module, not Continuum core",
    ),
    ClaimPattern(
        "full-main-replacement-claim",
        re.compile(
            r"\b(?:continuum\s+)?(?:m1|rework|this\s+(?:milestone|release|branch))"
            r"\b.{0,80}\b(?:full|fully|final)\s+replac(?:e|es|ement)\b.{0,80}"
            r"\b(?:old\s+)?`?main`?\b|"
            r"\b(?:continuum\s+)?(?:m1|rework|this\s+(?:milestone|release|branch))"
            r"\b.{0,80}\b(?:old\s+)?`?main`?\b.{0,80}"
            r"\b(?:full|fully|final)\s+replac(?:e|es|ement)\b|"
            r"\bfully\s+replaces\s+(?:old\s+)?`?main`?\b",
            re.IGNORECASE,
        ),
        "describe M1 as an intermediate milestone, not a final main replacement",
    ),
    ClaimPattern(
        "final-or-full-m1-release-claim",
        re.compile(
            r"\b(?:continuum\s+)?(?:m1|rework|this\s+(?:milestone|release|branch))"
            r"\b.{0,80}\b(?:final|full)\s+release\b|"
            r"\b(?:final|full)\s+release\b.{0,80}"
            r"\b(?:continuum\s+)?(?:m1|rework|this\s+(?:milestone|release|branch))\b|"
            r"\b(?:first|new)\s+full\s+release\b",
            re.IGNORECASE,
        ),
        "describe M1 as an intermediate milestone or pre-release, not a final/full release",
    ),
    ClaimPattern(
        "cloud-provider-release-claim",
        re.compile(
            r"\b(?:supports?|certif(?:y|ies|ied)|release[- ]supported)\b.{0,100}"
            r"\b(?:gcp|google cloud|aws)\b|"
            r"\b(?:gcp|google cloud|aws)\b.{0,100}"
            r"\b(?:supports?|certif(?:y|ies|ied)|release[- ]supported)\b",
            re.IGNORECASE,
        ),
        "do not claim GCP/AWS support without certified cloud evidence",
    ),
    ClaimPattern(
        "application-parity-release-claim",
        re.compile(
            r"\b(?:kubeedge|mist|openfaas)\b.{0,120}"
            r"\b(?:application|image[- ]classification|image/build)\b.{0,120}"
            r"\b(?:certif(?:y|ies|ied)|release[- ]supported)\b|"
            r"\b(?:certif(?:y|ies|ied)|release[- ]supported)\b.{0,120}"
            r"\b(?:kubeedge|mist|openfaas)\b.{0,120}"
            r"\b(?:application|image[- ]classification|image/build)\b",
            re.IGNORECASE,
        ),
        "certify only exact software-only subsets until full application rows have evidence",
    ),
    ClaimPattern(
        "full-qemu-parity-release-claim",
        re.compile(
            r"\b(?:full|all|complete)\b.{0,120}\bqemu\b.{0,120}"
            r"\b(?:parity|old[- ]main)\b.{0,120}"
            r"\b(?:certif(?:y|ies|ied)|release[- ]supported|supports?|complete)\b|"
            r"\bqemu\b.{0,120}\b(?:parity|old[- ]main)\b.{0,120}"
            r"\b(?:full|all|complete)\b.{0,120}"
            r"\b(?:certif(?:y|ies|ied)|release[- ]supported|supports?|complete)\b|"
            r"\bqemu\b.{0,120}\bparity\b.{0,120}\bcomplete\b",
            re.IGNORECASE,
        ),
        "claim only exact QEMU parity rows until all old-main QEMU rows have evidence",
    ),
    ClaimPattern(
        "all-yaml-examples-release-supported",
        re.compile(
            r"\ball\s+shipped\s+ya?ml\s+examples\s+are\s+release[- ]supported\b|"
            r"\bshipped\s+ya?ml\s+examples\s+are\s+release[- ]supported\b",
            re.IGNORECASE,
        ),
        "shipped examples are parser coverage unless matrix rows certify them",
    ),
    ClaimPattern(
        "module-readiness-overclaim",
        re.compile(
            r"\b(?:kubeedge|openfaas)\b.{0,100}"
            r"\b(?:explicit\s+edge\s+readiness|gateway\s+readiness|healthy\s+gateway)\b|"
            r"\b(?:explicit\s+edge\s+readiness|gateway\s+readiness|healthy\s+gateway)\b"
            r".{0,100}\b(?:kubeedge|openfaas)\b|"
            r"\bgateway\s+readiness\s+checks\b|"
            r"\bexplicit\s+edge\s+readiness\s+checks\b|"
            r"\bretained\s+readiness\s+snapshot\b",
            re.IGNORECASE,
        ),
        "claim only retained software-phase evidence unless readiness markers are explicit",
    ),
)

ALLOWED_CLAIM_CONTEXTS = {
    "qemu-core-claim": (
        re.compile(r"\bdo\s+not\s+claim\b", re.IGNORECASE),
        re.compile(
            r"\bqemu\b.{0,80}\b(?:is\s+)?not\s+(?:part\s+of\s+)?"
            r"(?:the\s+)?(?:continuum\s+)?core\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bqemu\b.{0,80}\bprovider\s+module\b.{0,80}\bnot\b.{0,80}"
            r"\b(?:continuum\s+)?core\b",
            re.IGNORECASE,
        ),
    ),
    "full-main-replacement-claim": (
        re.compile(r"\bdo\s+not\s+(?:claim|describe)\b", re.IGNORECASE),
        re.compile(r"\bnot\b.{0,80}\b(?:full|final)\s+replac", re.IGNORECASE),
        re.compile(r"\bnot\b.{0,80}\b(?:replac(?:e|es|ement))\b", re.IGNORECASE),
    ),
    "final-or-full-m1-release-claim": (
        re.compile(r"\bdo\s+not\s+(?:claim|describe)\b", re.IGNORECASE),
        re.compile(r"\bnot\b.{0,80}\b(?:final|full)\s+release\b", re.IGNORECASE),
    ),
    "cloud-provider-release-claim": (
        re.compile(r"\bdo\s+not\s+claim\b", re.IGNORECASE),
        re.compile(
            r"\bnot\b.{0,80}\b(?:release[- ]supported|certified|supported)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:need|needs|require|requires|required)\b.{0,120}\bevidence\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bevidence\b.{0,120}\bbefore\b.{0,120}\brelease[- ]supported\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bdecide\s+whether\b.{0,120}\bport/certify\b.{0,80}"
            r"\bdocument\s+as\s+historical\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:unclaimed|unverified)\b", re.IGNORECASE),
    ),
    "application-parity-release-claim": (
        re.compile(r"\bdo\s+not\s+claim\b", re.IGNORECASE),
        re.compile(r"\b(?:does\s+)?not\s+certif", re.IGNORECASE),
        re.compile(
            r"\bkubeedge\b.{0,120}\bcertified\s+only\s+for\b.{0,120}\bP-QEMU-06\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bcertified\s+only\s+for\b.{0,120}\bP-QEMU-06\b.{0,120}\bkubeedge\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bmist\b.{0,120}\bcertified\s+only\s+for\b.{0,120}\bP-QEMU-07\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bcertified\s+only\s+for\b.{0,120}\bP-QEMU-07\b.{0,120}\bmist\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:need|needs|require|requires|required)\b.{0,120}\bevidence\b",
            re.IGNORECASE,
        ),
        re.compile(r"\buntil\b.{0,120}\bevidence\b", re.IGNORECASE),
        re.compile(r"\b(?:unclaimed|unverified)\b", re.IGNORECASE),
    ),
    "full-qemu-parity-release-claim": (
        re.compile(r"\bdo\s+not\s+claim\b", re.IGNORECASE),
        re.compile(
            r"\bnot\b.{0,80}\b(?:full|all|complete)\b.{0,80}\bqemu\b",
            re.IGNORECASE,
        ),
        re.compile(r"\buntil\b.{0,120}\bevidence\b", re.IGNORECASE),
        re.compile(
            r"\b(?:need|needs|require|requires|required)\b.{0,120}\bevidence\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:unclaimed|unverified)\b", re.IGNORECASE),
    ),
    "module-readiness-overclaim": (
        re.compile(r"\bdo\s+not\s+claim\b", re.IGNORECASE),
        re.compile(r"\bdoes\s+not\s+retain\b", re.IGNORECASE),
        re.compile(r"\bdoes\s+not\s+certif", re.IGNORECASE),
        re.compile(r"\bbeyond\s+software[- ]phase\s+completion\b", re.IGNORECASE),
        re.compile(r"\bbefore\b.{0,120}\breadiness\b", re.IGNORECASE),
    ),
}


def _is_allowed_claim_context(kind: str, *lines: str) -> bool:
    """Return whether a matched claim appears in explicit non-claim context."""
    return any(
        pattern.search(line)
        for pattern in ALLOWED_CLAIM_CONTEXTS.get(kind, ())
        for line in lines
    )


def _strip_inline_code(line: str) -> str:
    return INLINE_CODE_RE.sub("", line)


def _iter_scannable_lines(path: Path, text: str) -> Iterable[tuple[int, str]]:
    """Yield doc lines excluding fenced code and release-note anti-examples."""
    in_fenced_code = False
    in_avoid_wording = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if path == RELEASE_NOTES_PATH and stripped.startswith("## "):
            in_avoid_wording = False
        if path == RELEASE_NOTES_PATH and stripped == "Avoid wording like:":
            in_avoid_wording = True
            continue
        if in_avoid_wording:
            continue
        if stripped.startswith("```"):
            in_fenced_code = not in_fenced_code
            continue
        if in_fenced_code:
            continue
        yield lineno, line


def _iter_existing_public_docs(root: Path) -> Iterable[tuple[Path, str]]:
    yielded_paths = set()
    for path in SCANNED_RELEASE_DOCS:
        full_path = root / path
        if full_path.exists():
            yielded_paths.add(path)
            yield path, full_path.read_text(encoding="utf-8")
    for doc_glob in ADDITIONAL_CLAIM_SCAN_GLOBS:
        for full_path in sorted(root.glob(doc_glob)):
            if not full_path.is_file():
                continue
            relative_path = full_path.relative_to(root)
            if relative_path in yielded_paths:
                continue
            yielded_paths.add(relative_path)
            yield relative_path, full_path.read_text(encoding="utf-8")


def _iter_release_evidence_docs(root: Path) -> Iterable[Path]:
    for full_path in sorted((root / "docs").glob("release_evidence_*.md")):
        relative_path = full_path.relative_to(root)
        if relative_path in PUBLIC_RELEASE_DOCS:
            continue
        yield relative_path


def _matrix_reference_issues(root: Path) -> list[ReleaseClaimIssue]:
    issues = []
    matrix_reference = MATRIX_PATH.as_posix()

    required_docs = set(MATRIX_REFERENCE_REQUIRED_DOCS)
    required_docs.update(_iter_release_evidence_docs(root))

    for path in sorted(required_docs):
        full_path = root / path
        if not full_path.exists():
            issues.append(
                ReleaseClaimIssue(
                    "release-doc-missing",
                    path.as_posix(),
                )
            )
            continue

        text = full_path.read_text(encoding="utf-8")
        if matrix_reference in text:
            continue
        issues.append(
            ReleaseClaimIssue(
                "release-doc-matrix-reference-missing",
                "%s must point support claims to %s" % (path.as_posix(), matrix_reference),
            )
        )

    return issues


def _unsupported_claim_issues(root: Path) -> list[ReleaseClaimIssue]:
    issues = []
    for path, text in _iter_existing_public_docs(root):
        for lineno, line in _iter_scannable_lines(path, text):
            scan_line = _strip_inline_code(line)
            for claim_pattern in CLAIM_PATTERNS:
                if not claim_pattern.regex.search(scan_line):
                    continue
                if _is_allowed_claim_context(claim_pattern.kind, scan_line, line):
                    continue
                issues.append(
                    ReleaseClaimIssue(
                        claim_pattern.kind,
                        "%s:%d: %s" % (path.as_posix(), lineno, claim_pattern.detail),
                    )
                )
    return issues


def find_release_claim_issues(root: Path = ROOT) -> list[ReleaseClaimIssue]:
    """Return release-facing wording drift issues."""
    root = root.resolve()
    issues = []
    issues.extend(_matrix_reference_issues(root))
    issues.extend(_unsupported_claim_issues(root))
    return issues


def main() -> int:
    """Run the public release-claims hygiene check."""
    issues = find_release_claim_issues(ROOT)
    for issue in issues:
        print("%s: %s" % (issue.kind, issue.detail))
    print("TOTAL_RELEASE_CLAIM_ISSUES=%d" % (len(issues)))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
