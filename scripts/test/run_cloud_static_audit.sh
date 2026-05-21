#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
TIMESTAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
REPORT_DIR="logs/cloud_static_audit"
REPORT="$REPORT_DIR/cloud_static_audit_$TIMESTAMP.md"
WORK_DIR="$(mktemp -d)"

trap 'rm -rf "$WORK_DIR"' EXIT
mkdir -p "$REPORT_DIR"

keys=()
titles=()
required_flags=()
return_codes=()
output_files=()
commands=()
required_failed=0

run_capture() {
    local key="$1"
    local title="$2"
    local required="$3"
    shift 3

    local output_file="$WORK_DIR/$key.txt"
    local command_display
    printf -v command_display "%q " "$@"

    set +e
    "$@" >"$output_file" 2>&1
    local rc=$?
    set -e

    keys+=("$key")
    titles+=("$title")
    required_flags+=("$required")
    return_codes+=("$rc")
    output_files+=("$output_file")
    commands+=("${command_display% }")

    if [ "$required" = "required" ] && [ "$rc" -ne 0 ]; then
        required_failed=1
    fi
}

status_for() {
    local key="$1"
    local required="$2"
    local rc="$3"
    local output_file="$4"

    if [ "$required" = "required" ]; then
        if [ "$rc" -eq 0 ]; then
            echo "PASS"
        else
            echo "FAIL ($rc)"
        fi
        return
    fi

    if [ "$key" = "todo" ]; then
        if [ "$rc" -eq 0 ]; then
            echo "MATCHES FOUND ($(wc -l <"$output_file"))"
        elif [ "$rc" -eq 1 ]; then
            echo "NO MATCHES"
        else
            echo "ERROR ($rc)"
        fi
        return
    fi

    if [ "$rc" -eq 0 ]; then
        echo "OK"
    else
        echo "FINDINGS OR UNAVAILABLE ($rc)"
    fi
}

print_status_line() {
    local index="$1"
    local status

    status="$(
        status_for \
            "${keys[$index]}" \
            "${required_flags[$index]}" \
            "${return_codes[$index]}" \
            "${output_files[$index]}"
    )"
    echo "- ${titles[$index]}: $status"
}

compile_files=(
    continuum.py
    input/configuration/*.py
    resource_manager/*.py
    infrastructure/*.py
    application/runtime_helpers.py
    scripts/test/run_tests.py
    scripts/test/check_docs_paths.py
    scripts/test/verify_network_profiles.py
    scripts/test/support/*.py
    scripts/test/unit/*.py
    scripts/test/e2e/*.py
)

run_capture compile "compile sweep" required \
    "$PYTHON" -m py_compile "${compile_files[@]}"
run_capture unit_unittest "unit unittest discovery" required \
    env PYTHONPATH=. "$PYTHON" -m unittest discover scripts/test/unit
run_capture e2e_unittest "e2e unittest discovery" required \
    env PYTHONPATH=. "$PYTHON" -m unittest discover scripts/test/e2e
run_capture unittest "combined unittest discovery" required \
    env PYTHONPATH=. "$PYTHON" -m unittest discover scripts/test
run_capture docs "docs path reference check" required \
    "$PYTHON" scripts/test/check_docs_paths.py
run_capture suites "configured suite catalog" required \
    "$PYTHON" scripts/test/run_tests.py --list-suites

run_capture unit_pytest "unit pytest suite" optional \
    env PYTHONPATH=. pytest -q scripts/test/unit
run_capture e2e_pytest "e2e pytest suite" optional \
    env PYTHONPATH=. pytest -q scripts/test/e2e
run_capture pytest "combined pytest suite" optional \
    env PYTHONPATH=. pytest -q scripts/test
run_capture todo "TODO/FIXME debt scan" optional \
    rg -n "TODO|FIXME|TBD|XXX" \
        docs input application infrastructure resource_manager continuum.py scripts/test \
        -g "!logs/**" \
        -g "!docs/cloud_audit_report_*.md" \
        -g "!scripts/test/run_cloud_static_audit.sh"
run_capture yamllint "YAML lint baseline" optional \
    yamllint -c sysconfig/yamllint.yml configs playbooks roles \
        application/image_classification/launch_benchmark_kubernetes.yml \
        application/text_translation/launch_benchmark_kubernetes.yml
run_capture ansible_lint "Ansible lint baseline" optional \
    env XDG_CACHE_HOME=/tmp/continuum-xdg-cache \
        ANSIBLE_LOCAL_TEMP=/tmp/continuum-ansible-local \
        ANSIBLE_REMOTE_TEMP=/tmp/continuum-ansible-remote \
        ansible-lint -c .ansible-lint playbooks roles \
        application/image_classification/launch_benchmark_kubernetes.yml \
        application/text_translation/launch_benchmark_kubernetes.yml
run_capture prereq_smoke "smoke suite prerequisites" optional \
    "$PYTHON" scripts/test/run_tests.py --check-prereqs --suite smoke
run_capture prereq_benchmark "benchmark smoke suite prerequisites" optional \
    "$PYTHON" scripts/test/run_tests.py --check-prereqs --suite benchmark_smoke
run_capture prereq_network "network validation suite prerequisites" optional \
    "$PYTHON" scripts/test/run_tests.py --check-prereqs --suite network_validation

{
    echo "# Cloud Static Audit Report - $TIMESTAMP"
    echo
    echo "## Scope"
    echo "Cloud-safe static checks only. This runner does not start Continuum VM/runtime execution."
    echo
    echo "## Required Gates"
    for index in "${!keys[@]}"; do
        if [ "${required_flags[$index]}" = "required" ]; then
            print_status_line "$index"
        fi
    done
    echo
    echo "## Informational Checks"
    for index in "${!keys[@]}"; do
        if [ "${required_flags[$index]}" != "required" ]; then
            print_status_line "$index"
        fi
    done
    echo
    echo "## Commands Executed"
    for index in "${!keys[@]}"; do
        echo "$((index + 1)). ${commands[$index]}"
    done
    echo
    echo "## Output Excerpts"
    for index in "${!keys[@]}"; do
        echo
        echo "### ${titles[$index]}"
        echo '```'
        tail -n 160 "${output_files[$index]}"
        echo '```'
    done
} >"$REPORT"

echo "Wrote $REPORT"
exit "$required_failed"
