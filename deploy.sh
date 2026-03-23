#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

STATE_DIR=".deploy-state"
STATE_FILE="${STATE_DIR}/last_deployed_sha"
PRIMARY_PUBLIC_HOST="it-app.movedocs.com"
PRIMARY_PUBLIC_BASE_URL="https://${PRIMARY_PUBLIC_HOST}"

MODE="auto"
BUILD_FLAGS=()

usage() {
    cat <<'EOF'
Usage: ./deploy.sh [--backend | --frontend | --full] [--no-cache]

Default behavior auto-detects deploy scope from files changed since the last
successful deploy SHA in .deploy-state/last_deployed_sha.
EOF
}

for arg in "$@"; do
    case "$arg" in
        --backend|--frontend|--full)
            if [[ "$MODE" != "auto" ]]; then
                echo "ERROR: only one of --backend, --frontend, or --full may be used."
                exit 1
            fi
            MODE="${arg#--}"
            ;;
        --no-cache)
            BUILD_FLAGS+=(--no-cache)
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument '$arg'"
            usage
            exit 1
            ;;
    esac
done

echo "=== OIT Helpdesk Dashboard — Deploy ==="

if [[ ! -f backend/.env ]]; then
    echo "ERROR: backend/.env not found."
    echo "  cp backend/.env.example backend/.env"
    echo "  Then fill in your production values."
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker is not installed."
    echo "  curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "ERROR: git is required for scope-aware deploys."
    exit 1
fi

CURRENT_SHA="$(git rev-parse HEAD)"

dedupe_lines() {
    awk 'NF && !seen[$0]++'
}

collect_changed_files() {
    local base_sha="$1"
    {
        git diff --name-only "${base_sha}...HEAD" -- || true
        git diff --name-only HEAD -- || true
        git ls-files --others --exclude-standard || true
    } | dedupe_lines
}

classify_mode() {
    local backend_changed=0
    local frontend_changed=0
    local full_changed=0
    local file

    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        case "$file" in
            .deploy-state/*|docs/*|*.md)
                ;;
            backend/*|Dockerfile.backend)
                backend_changed=1
                ;;
            frontend/*|Dockerfile.frontend|frontend.nginx.conf)
                frontend_changed=1
                ;;
            deploy.sh)
                ;;
            docker-compose.yml|Caddyfile|Dockerfile.caddy|.dockerignore)
                full_changed=1
                ;;
            *)
                full_changed=1
                ;;
        esac
    done

    if [[ "$full_changed" == "1" ]]; then
        echo "full"
    elif [[ "$backend_changed" == "1" && "$frontend_changed" == "1" ]]; then
        echo "mixed"
    elif [[ "$backend_changed" == "1" ]]; then
        echo "backend"
    elif [[ "$frontend_changed" == "1" ]]; then
        echo "frontend"
    else
        echo "none"
    fi
}

if [[ "$MODE" == "auto" ]]; then
    if [[ ! -f "$STATE_FILE" ]]; then
        echo ">>> No recorded deploy SHA found; defaulting to full deploy."
        MODE="full"
    else
        LAST_DEPLOYED_SHA="$(tr -d '[:space:]' < "$STATE_FILE")"
        if ! git rev-parse --verify "${LAST_DEPLOYED_SHA}^{commit}" >/dev/null 2>&1; then
            echo ">>> Recorded deploy SHA is not available locally; defaulting to full deploy."
            MODE="full"
        else
            CHANGED_FILES="$(collect_changed_files "$LAST_DEPLOYED_SHA")"
            MODE="$(printf '%s\n' "$CHANGED_FILES" | classify_mode)"
            if [[ "$MODE" == "none" ]]; then
                echo ">>> Nothing deployable changed since the last successful deploy."
                exit 0
            fi
            echo ">>> Auto-detected deploy scope: $MODE"
        fi
    fi
fi

BACKEND_REQUIRED=0
FRONTEND_REQUIRED=0
FULL_STACK=0

case "$MODE" in
    backend)
        BACKEND_REQUIRED=1
        ;;
    frontend)
        FRONTEND_REQUIRED=1
        ;;
    mixed)
        BACKEND_REQUIRED=1
        FRONTEND_REQUIRED=1
        ;;
    full)
        BACKEND_REQUIRED=1
        FRONTEND_REQUIRED=1
        FULL_STACK=1
        ;;
    *)
        echo "ERROR: unsupported deploy mode '$MODE'"
        exit 1
        ;;
esac

check_host_ollama() {
    echo ">>> Checking Ollama on the host..."
    if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null; then
        echo "ERROR: Ollama is not reachable on the host at http://127.0.0.1:11434."
        echo "  Start Ollama and make sure it is serving before deploying."
        exit 1
    fi
}

verify_backend_ollama() {
    echo ">>> Verifying backend container can reach Ollama..."
    if ! docker compose exec -T backend python3 - <<'PY'
import json
import os
import sys
import urllib.request

base = os.environ.get("OLLAMA_BASE_URL", "").rstrip("/")
model = os.environ.get("OLLAMA_MODEL", "").strip()
if not base:
    print("OLLAMA_BASE_URL is not set in the backend container.")
    sys.exit(1)
if not model:
    print("OLLAMA_MODEL is not set in the backend container.")
    sys.exit(1)

url = f"{base}/api/tags"
try:
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200:
            print(f"Ollama check returned HTTP {response.status} for {url}")
            sys.exit(1)
        payload = json.loads(response.read().decode("utf-8", "ignore"))
except Exception as exc:
    print(f"Failed to reach Ollama from backend container at {url}: {exc}")
    sys.exit(1)

print(f"Ollama reachable from backend container at {url}")
models = {entry.get("model") or entry.get("name") for entry in payload.get("models") or []}
print(f"Available Ollama models: {sorted(m for m in models if m)}")
if model not in models:
    print(f"Configured Ollama model '{model}' is not pulled on the host.")
    sys.exit(1)
PY
    then
        echo "ERROR: Backend container cannot reach Ollama."
        echo "  Check docker networking, OLLAMA_BASE_URL, and that the configured model is pulled."
        exit 1
    fi
}

wait_for_http() {
    local url="$1"
    local label="$2"
    local attempts="${3:-120}"

    echo ">>> Waiting for ${label}..."
    for _ in $(seq 1 "$attempts"); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            echo ">>> ${label} is ready"
            return 0
        fi
        printf "."
        sleep 1
    done
    echo ""
    echo "ERROR: Timed out waiting for ${label} (${url})"
    return 1
}

curl_public_local() {
    local url="$1"
    curl -fsS --connect-timeout 5 --max-time 10 \
        --resolve "${PRIMARY_PUBLIC_HOST}:443:127.0.0.1" "$url"
}

wait_for_public_https() {
    local path="$1"
    local label="$2"
    local attempts="${3:-120}"

    local url="${PRIMARY_PUBLIC_BASE_URL}${path}"

    echo ">>> Waiting for ${label}..."
    for _ in $(seq 1 "$attempts"); do
        if curl_public_local "$url" >/dev/null 2>&1; then
            echo ">>> ${label} is ready"
            return 0
        fi
        printf "."
        sleep 1
    done
    echo ""
    echo "ERROR: Timed out waiting for ${label} (${url})"
    return 1
}

print_readiness() {
    if curl_public_local "${PRIMARY_PUBLIC_BASE_URL}/api/health/ready"; then
        echo ""
        return 0
    fi
    echo ""
    echo ">>> Readiness still warming:"
    curl --silent --show-error --resolve "${PRIMARY_PUBLIC_HOST}:443:127.0.0.1" \
        "${PRIMARY_PUBLIC_BASE_URL}/api/health/ready" || true
    echo ""
}

build_services() {
    docker compose build "${BUILD_FLAGS[@]}" "$@"
}

restart_services() {
    docker compose up -d --remove-orphans "$@"
}

restart_services_no_deps() {
    docker compose up -d --no-deps --remove-orphans "$@"
}

if [[ "$BACKEND_REQUIRED" == "1" ]]; then
    check_host_ollama
fi

case "$MODE" in
    backend)
        echo ">>> Building backend image..."
        build_services backend
        echo ">>> Restarting backend only..."
        restart_services_no_deps backend
        ;;
    frontend)
        echo ">>> Building frontend image..."
        build_services frontend
        echo ">>> Restarting frontend only..."
        restart_services_no_deps frontend
        ;;
    mixed)
        echo ">>> Building backend and frontend images..."
        build_services backend frontend
        echo ">>> Restarting frontend, then backend..."
        restart_services_no_deps frontend
        restart_services_no_deps backend
        ;;
    full)
        echo ">>> Building caddy, backend, and frontend images..."
        build_services caddy backend frontend
        echo ">>> Restarting full stack..."
        restart_services caddy backend frontend
        ;;
esac

if [[ "$BACKEND_REQUIRED" == "1" ]]; then
    verify_backend_ollama
    wait_for_public_https "/api/health" "API liveness"
    print_readiness
fi

if [[ "$FRONTEND_REQUIRED" == "1" || "$FULL_STACK" == "1" ]]; then
    wait_for_public_https "/" "frontend shell"
fi

mkdir -p "$STATE_DIR"
printf '%s\n' "$CURRENT_SHA" > "$STATE_FILE"

echo ""
echo "=== DEPLOYED SUCCESSFULLY ==="
echo "  Mode:      $MODE"
echo "  Dashboard: https://it-app.movedocs.com"
echo "  OasisDev:  https://oasisdev.movedocs.com"
echo "  Azure:     https://azure.movedocs.com"
echo "  Health:    https://it-app.movedocs.com/api/health"
echo "  Ready:     https://it-app.movedocs.com/api/health/ready"
echo ""
docker compose ps
