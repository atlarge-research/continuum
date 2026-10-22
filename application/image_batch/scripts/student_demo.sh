#!/usr/bin/env bash
# Keep the local demo environment in one place; Continuum provisioning stays explicit.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash application/image_batch/scripts/student_demo.sh [--config PATH] COMMAND [ARGS...]

Commands:
  prepare   Build images, configure the existing cluster, and start the demo.
  check     Check configuration and cluster readiness.
  kubectl   Run kubectl against the demo cluster.
  url       Print the image-processing service URL.
  capture   Record a demo run.
  python    Run Python in the demo environment.
  --help    Show this help without creating a runtime.

The default config is logs/student-demo/cluster.cfg in the repository.
An explicit relative --config path is relative to your current directory.
Only prepare creates the runtime and installs its dependencies; it requires Python 3.10.
EOF
}

if [[ $# -eq 0 ]]; then
    usage >&2
    exit 2
fi

repository=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)
config="$repository/logs/student-demo/cluster.cfg"
if [[ "$1" == --config ]]; then
    if [[ $# -lt 2 || -z "$2" ]]; then
        printf '%s\n' 'Error: --config requires a path.' >&2
        exit 2
    fi
    config=$(realpath -m -- "$2")
    shift 2
fi

case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
    prepare|check|kubectl|url|capture|python) ;;
    *)
        usage >&2
        exit 2
        ;;
esac

runtime="$(dirname -- "$config")/runtime"
if [[ "$1" == prepare ]]; then
    if [[ ! -f "$config" ]]; then
        printf 'Error: config does not exist: %s\n' "$config" >&2
        exit 1
    fi
    if [[ ! -x "$runtime/bin/python" ]]; then
        if ! command -v python3.10 >/dev/null 2>&1; then
            printf '%s\n' 'Error: prepare requires python3.10 with venv support.' >&2
            exit 1
        fi
        python3.10 -m venv "$runtime"
    fi
    "$runtime/bin/python" -m pip install \
        -r "$repository/application/image_batch/requirements-analysis.txt" PyYAML==6.0.3
elif [[ ! -x "$runtime/bin/python" ]]; then
    printf 'Error: demo runtime is missing; run this launcher with --config "%s" prepare first.\n' \
        "$config" >&2
    exit 1
fi

export PYTHONPATH="$repository/application/image_batch/src:$repository"
export OPENDC_RUNTIME=fns-demo
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
cd -- "$repository"
exec "$runtime/bin/python" -m student_demo --config "$config" "$@"
