#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./release.sh --message "commit message" [--no-cache] [--allow-empty]

Stages all changes, creates a git commit, pushes the current branch, and then
calls ./deploy.sh.

Options:
  -m, --message      Commit message to use
      --no-cache     Pass --no-cache through to ./deploy.sh
      --allow-empty  Create an empty commit if nothing changed after staging
  -h, --help         Show this help text
EOF
}

require_command() {
    local name="$1"
    if ! command -v "$name" > /dev/null 2>&1; then
        echo "ERROR: Required command not found: $name"
        exit 1
    fi
}

cd "$(dirname "$0")"

commit_message=""
deploy_args=()
allow_empty=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--message)
            shift
            if [[ $# -eq 0 || -z "${1:-}" ]]; then
                echo "ERROR: --message requires a value"
                usage
                exit 1
            fi
            commit_message="$1"
            ;;
        --no-cache)
            deploy_args+=("--no-cache")
            ;;
        --allow-empty)
            allow_empty=1
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

if [[ -z "$commit_message" ]]; then
    echo "ERROR: A commit message is required"
    usage
    exit 1
fi

require_command git

if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "ERROR: release.sh must be run inside a git repository"
    exit 1
fi

current_branch="$(git branch --show-current)"
if [[ -z "$current_branch" ]]; then
    echo "ERROR: Cannot release from a detached HEAD"
    exit 1
fi

echo ">>> Staging changes..."
git add -A

if git diff --cached --quiet; then
    if [[ "$allow_empty" -ne 1 ]]; then
        echo "ERROR: No staged changes to commit. Use --allow-empty to force an empty commit."
        exit 1
    fi
fi

echo ">>> Creating commit on $current_branch..."
if [[ "$allow_empty" -eq 1 ]]; then
    git commit --allow-empty -m "$commit_message"
else
    git commit -m "$commit_message"
fi

if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' > /dev/null 2>&1; then
    echo ">>> Pushing to existing upstream..."
    git push
else
    if git remote get-url origin > /dev/null 2>&1; then
        echo ">>> Pushing and setting upstream to origin/$current_branch..."
        git push --set-upstream origin "$current_branch"
    else
        echo "ERROR: No upstream configured and no origin remote found"
        exit 1
    fi
fi

echo ">>> Starting redeploy..."
./deploy.sh "${deploy_args[@]}"