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

    local rc
    if "$@" >"$output_file" 2>&1; then
        rc=0
    else
        rc=$?
    fi

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
    scripts/test/check_release_claims.py
    scripts/test/check_release_evidence_artifacts.py
    scripts/test/check_release_matrix.py
    scripts/test/check_release_pretag.py
    scripts/test/verify_network_profiles.py
    scripts/test/support/*.py
    scripts/test/unit/*.py
    scripts/test/e2e/*.py
)

run_capture compile "compile sweep" required \
    "$PYTHON" -B -m py_compile "${compile_files[@]}"
run_capture shell_syntax_audit "cloud audit shell syntax check" required \
    bash -n scripts/test/run_cloud_static_audit.sh
run_capture shell_syntax_smoke "smoke wrapper shell syntax check" required \
    sh -n scripts/test/run_smoke_host.sh
run_capture shell_syntax_host_setup "host setup shell syntax check" required \
    sh -n scripts/test/setup_agent_host.sh
run_capture diff_check "git diff whitespace check" required \
    git diff --check
run_capture unit_unittest "unit unittest discovery" required \
    env PYTHONPATH=. "$PYTHON" -B -m unittest discover scripts/test/unit
run_capture e2e_unittest "e2e unittest discovery" required \
    env PYTHONPATH=. "$PYTHON" -B -m unittest discover scripts/test/e2e
run_capture unittest "combined unittest discovery" required \
    env PYTHONPATH=. "$PYTHON" -B -m unittest discover scripts/test
run_capture docs "docs path reference check" required \
    "$PYTHON" -B scripts/test/check_docs_paths.py
run_capture release_claims "public release-claims check" required \
    "$PYTHON" -B scripts/test/check_release_claims.py
run_capture release_matrix "release certification matrix check" required \
    "$PYTHON" -B scripts/test/check_release_matrix.py
run_capture suites "configured suite catalog" required \
    "$PYTHON" -B scripts/test/run_tests.py --list-suites

run_capture release_evidence_artifacts "release evidence artifact audit" optional \
    "$PYTHON" -B scripts/test/check_release_evidence_artifacts.py
run_capture release_pretag "M1 pre-tag readiness check" optional \
    "$PYTHON" -B scripts/test/check_release_pretag.py
run_capture unit_pytest "unit pytest suite" optional \
    env PYTHONPATH=. pytest -q scripts/test/unit
run_capture e2e_pytest "e2e pytest suite" optional \
    env PYTHONPATH=. pytest -q scripts/test/e2e
run_capture pytest "combined pytest suite" optional \
    env PYTHONPATH=. pytest -q scripts/test

todo_scan() {
    if command -v rg >/dev/null 2>&1; then
        rg -n "TODO|FIXME|TBD|XXX" \
            docs input application infrastructure resource_manager continuum.py scripts/test \
            -g "!logs/**" \
            -g "!docs/cloud_audit_report_*.md" \
            -g "!scripts/test/run_cloud_static_audit.sh"
        return
    fi

    grep -RInE \
        --exclude="cloud_audit_report_*.md" \
        --exclude="run_cloud_static_audit.sh" \
        "TODO|FIXME|TBD|XXX" \
        docs input application infrastructure resource_manager continuum.py scripts/test
}

run_capture todo "TODO/FIXME debt scan" optional todo_scan
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
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite smoke
run_capture prereq_benchmark "benchmark smoke suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite benchmark_smoke
run_capture prereq_network "network validation suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite network_validation
run_capture prereq_qemu_infra_parity "QEMU infra parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_infra_parity
run_capture prereq_qemu_k8s_nobench_parity "QEMU Kubernetes no-benchmark parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_k8s_nobench_parity
run_capture prereq_qemu_kubeedge_software_parity "QEMU KubeEdge software parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_kubeedge_software_parity
run_capture prereq_qemu_mist_software_parity "QEMU Mist software parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_mist_software_parity
run_capture prereq_qemu_endpoint_software_parity "QEMU endpoint-runtime software parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_endpoint_software_parity
run_capture prereq_qemu_openfaas_software_parity "QEMU OpenFaaS software parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_openfaas_software_parity
run_capture prereq_qemu_openfaas_image_local_parity "QEMU OpenFaaS local image parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_openfaas_image_local_parity
run_capture prereq_qemu_kubecontrol_empty_parity "QEMU kubecontrol empty parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/prime_local_registry_cache.py \
        --suite qemu_kubecontrol_empty_parity --check-only
run_capture prereq_qemu_kubecontrol_empty_trace_parity "QEMU kubecontrol empty trace parity suite prerequisites" optional \
    "$PYTHON" -B scripts/test/prime_local_registry_cache.py \
        --suite qemu_kubecontrol_empty_trace_parity --check-only

forced_prefetch_notice() {
    cat <<'EOF'
OpenFaaS application parity row P-QEMU-10 is not certified by this cloud-safe
audit. Cache readiness is only a prerequisite signal for that row;
certification still requires the dedicated smoke-user wrapper context plus
retained VM/application evidence on the documented resource shape. Cache-backed
P-QEMU-05 and P-QEMU-08 are certified separately by retained wrapper evidence.
See docs/release_certification_matrix.md for the active blockers.
EOF
}

run_capture prereq_forced_prefetch_notice "OpenFaaS image parity certification notice" optional \
    forced_prefetch_notice
run_capture prereq_qemu_k8s_image_parity "QEMU Kubernetes image parity registry-cache prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_k8s_image_parity
run_capture prereq_qemu_kubeedge_image_parity "QEMU KubeEdge image parity registry-cache prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_kubeedge_image_parity
run_capture prereq_qemu_mist_image_parity "QEMU Mist image parity registry-cache prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_mist_image_parity
run_capture prereq_qemu_endpoint_image_parity "QEMU endpoint image parity registry-cache prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_endpoint_image_parity
run_capture prereq_qemu_openfaas_image_parity "QEMU OpenFaaS image parity registry-cache prerequisites" optional \
    "$PYTHON" -B scripts/test/run_tests.py --check-prereqs --suite qemu_openfaas_image_parity

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
