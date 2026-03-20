#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash ./scripts/run_secret_scan.sh [--working-tree] [--full-history]

Runs Gitleaks against the repository using a local binary when available,
or the official container image as a fallback.
EOF
}

cd "$(dirname "$0")/.."
repo_root="$PWD"
image="${GITLEAKS_IMAGE:-ghcr.io/gitleaks/gitleaks:v8.28.0}"

scan_working_tree=0
scan_full_history=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --working-tree)
            scan_working_tree=1
            ;;
        --full-history)
            scan_full_history=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
    shift
done

if [[ "$scan_working_tree" -eq 0 && "$scan_full_history" -eq 0 ]]; then
    scan_working_tree=1
    scan_full_history=1
fi

run_gitleaks_local() {
    local mode="$1"
    if [[ "$mode" == "history" ]]; then
        gitleaks detect --source "$repo_root" --log-opts="--all" --redact --exit-code 1
    else
        gitleaks detect --source "$repo_root" --redact --exit-code 1
    fi
}

run_gitleaks_docker() {
    local mode="$1"
    if ! command -v docker >/dev/null 2>&1; then
        echo "ERROR: gitleaks is not installed and docker is unavailable."
        exit 1
    fi
    if [[ "$mode" == "history" ]]; then
        docker run --rm -v "$repo_root:/repo" -w /repo "$image" \
            detect --source /repo --log-opts="--all" --redact --exit-code 1
    else
        docker run --rm -v "$repo_root:/repo" -w /repo "$image" \
            detect --source /repo --redact --exit-code 1
    fi
}

run_scan() {
    local mode="$1"
    echo ">>> Gitleaks scan: $mode"
    if command -v gitleaks >/dev/null 2>&1; then
        run_gitleaks_local "$mode"
    else
        run_gitleaks_docker "$mode"
    fi
}

if [[ "$scan_working_tree" -eq 1 ]]; then
    run_scan working-tree
fi

if [[ "$scan_full_history" -eq 1 ]]; then
    run_scan history
fi
