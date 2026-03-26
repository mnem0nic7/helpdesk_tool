#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

STATE_DIR=".deploy-state"
STATE_FILE="${STATE_DIR}/last_deployed_sha"
ACTIVE_COLOR_FILE="${STATE_DIR}/active_color"
ACTIVE_UPSTREAMS_FILE="${STATE_DIR}/active_upstreams.caddy"
PRIMARY_PUBLIC_HOST="it-app.movedocs.com"
PRIMARY_PUBLIC_BASE_URL="https://${PRIMARY_PUBLIC_HOST}"

MODE="auto"
BUILD_FLAGS=()
CHANGED_FILES=""

usage() {
    cat <<'EOF'
Usage: ./deploy.sh [--backend | --frontend | --full] [--no-cache]

Default behavior auto-detects deploy scope from files changed since the last
successful deploy SHA in .deploy-state/last_deployed_sha.

Blue-green deploy notes:
- backend/frontend deploys always build and switch the full inactive app color
- the previous color stays online until the next deploy for instant rollback
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

echo "=== OIT Helpdesk Dashboard — Blue-Green Deploy ==="

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
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}"

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
                full_changed=1
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

APP_REQUIRED=1
VERIFY_OLLAMA=1
CADDY_IMAGE_REQUIRED=0

if [[ "$MODE" == "full" ]]; then
    if [[ -z "$CHANGED_FILES" ]]; then
        CADDY_IMAGE_REQUIRED=1
    elif printf '%s\n' "$CHANGED_FILES" | grep -qx 'Dockerfile.caddy'; then
        CADDY_IMAGE_REQUIRED=1
    fi
fi

ensure_state_dir() {
    mkdir -p "$STATE_DIR"
}

is_valid_color() {
    [[ "$1" == "blue" || "$1" == "green" ]]
}

read_active_color() {
    local color="blue"
    if [[ -f "$ACTIVE_COLOR_FILE" ]]; then
        color="$(tr -d '[:space:]' < "$ACTIVE_COLOR_FILE")"
    fi
    if ! is_valid_color "$color"; then
        color="blue"
    fi
    printf '%s\n' "$color"
}

write_active_color() {
    local color="$1"
    ensure_state_dir
    printf '%s\n' "$color" > "$ACTIVE_COLOR_FILE"
}

other_color() {
    if [[ "$1" == "blue" ]]; then
        printf 'green\n'
    else
        printf 'blue\n'
    fi
}

backend_service_for_color() {
    printf 'backend_%s\n' "$1"
}

frontend_service_for_color() {
    printf 'frontend_%s\n' "$1"
}

render_active_upstreams() {
    local color="$1"
    local backend_service frontend_service
    backend_service="$(backend_service_for_color "$color")"
    frontend_service="$(frontend_service_for_color "$color")"
    ensure_state_dir
    cat > "$ACTIVE_UPSTREAMS_FILE" <<EOF
(active_upstreams) {
	@api path /api/*
	reverse_proxy @api ${backend_service}:8000 {
		header_up Host {http.request.host}
		header_up X-Forwarded-Host {http.request.host}
		header_up X-Forwarded-Proto {http.request.scheme}
	}

	reverse_proxy ${frontend_service}:80 {
		header_up Host {http.request.host}
		header_up X-Forwarded-Host {http.request.host}
		header_up X-Forwarded-Proto {http.request.scheme}
	}
}
EOF
}

ensure_active_upstreams_file() {
    ensure_state_dir
    local color
    color="$(read_active_color)"
    if [[ ! -f "$ACTIVE_UPSTREAMS_FILE" ]]; then
        render_active_upstreams "$color"
    fi
}

read_env_var() {
    local name="$1"
    python3 - "$name" backend/.env <<'PY'
import sys
from pathlib import Path

target = sys.argv[1]
path = Path(sys.argv[2])
if not path.exists():
    sys.exit(0)

for raw in path.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != target:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    print(value)
    break
PY
}

DEPLOY_CONTROL_SECRET="$(read_env_var DEPLOY_CONTROL_SECRET)"
if [[ -z "$DEPLOY_CONTROL_SECRET" ]]; then
    echo "ERROR: DEPLOY_CONTROL_SECRET must be set in backend/.env for blue-green deploy control."
    exit 1
fi

service_container_id() {
    docker compose ps -q "$1" 2>/dev/null | head -n1
}

legacy_service_container_id() {
    local service="$1"
    docker ps -q \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
        --filter "label=com.docker.compose.service=${service}" | head -n1
}

service_is_running() {
    [[ -n "$(service_container_id "$1")" ]]
}

legacy_service_is_running() {
    [[ -n "$(legacy_service_container_id "$1")" ]]
}

service_ip() {
    local service="$1"
    local container_id
    container_id="$(service_container_id "$service")"
    if [[ -z "$container_id" ]]; then
        return 1
    fi
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container_id"
}

legacy_service_ip() {
    local service="$1"
    local container_id
    container_id="$(legacy_service_container_id "$service")"
    if [[ -z "$container_id" ]]; then
        return 1
    fi
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container_id"
}

render_legacy_upstreams() {
    local backend_ip frontend_ip
    backend_ip="$(legacy_service_ip backend)"
    frontend_ip="$(legacy_service_ip frontend)"
    ensure_state_dir
    cat > "$ACTIVE_UPSTREAMS_FILE" <<EOF
(active_upstreams) {
	@api path /api/*
	reverse_proxy @api ${backend_ip}:8000 {
		header_up Host {http.request.host}
		header_up X-Forwarded-Host {http.request.host}
		header_up X-Forwarded-Proto {http.request.scheme}
	}

	reverse_proxy ${frontend_ip}:80 {
		header_up Host {http.request.host}
		header_up X-Forwarded-Host {http.request.host}
		header_up X-Forwarded-Proto {http.request.scheme}
	}
}
EOF
}

service_local_http_ok() {
    local service="$1"
    local port="$2"
    local path="$3"
    if [[ "$service" == backend_* ]]; then
        docker compose exec -T "$service" python3 - "$port" "$path" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

port = sys.argv[1]
path = sys.argv[2]
with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
    if response.status < 200 or response.status >= 400:
        raise SystemExit(1)
PY
        return $?
    fi
    docker compose exec -T "$service" sh -lc "wget -q -O /dev/null http://127.0.0.1:${port}${path}" >/dev/null 2>&1
}

backend_local_get_json() {
    local service="$1"
    local path="$2"
    docker compose exec -T "$service" python3 - "$path" <<'PY'
import sys
import urllib.request

path = sys.argv[1]
with urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=10) as response:
    print(response.read().decode("utf-8", "ignore"))
PY
}

wait_for_container_http() {
    local service="$1"
    local port="$2"
    local path="$3"
    local label="$4"
    local attempts="${5:-120}"

    echo ">>> Waiting for ${label}..."
    for _ in $(seq 1 "$attempts"); do
        if service_local_http_ok "$service" "$port" "$path"; then
            echo ">>> ${label} is ready"
            return 0
        fi
        printf "."
        sleep 1
    done
    echo ""
    echo "ERROR: Timed out waiting for ${label}"
    return 1
}

wait_for_backend_role() {
    local service="$1"
    local expected_role="$2"
    local attempts="${3:-120}"

    echo ">>> Waiting for ${service} to become ${expected_role}..."
    for _ in $(seq 1 "$attempts"); do
        local payload
        payload="$(backend_local_get_json "$service" "/api/health/ready" 2>/dev/null || true)"
        if [[ -n "$payload" ]] && python3 -c '
import json
import sys

expected = sys.argv[1]
payload = json.load(sys.stdin)
runtime = payload.get("runtime") or {}
ok = payload.get("status") == "ready" and runtime.get("role") == expected
raise SystemExit(0 if ok else 1)
' "$expected_role" <<<"$payload"
        then
            echo ">>> ${service} is ${expected_role} and ready"
            return 0
        fi
        printf "."
        sleep 1
    done
    echo ""
    echo "ERROR: Timed out waiting for ${service} to become ${expected_role}"
    return 1
}

post_internal_runtime() {
    local service="$1"
    local action="$2"
    docker compose exec -T "$service" python3 - "$action" "$DEPLOY_CONTROL_SECRET" <<'PY'
import sys
import urllib.request

action = sys.argv[1]
secret = sys.argv[2]
request = urllib.request.Request(
    f"http://127.0.0.1:8000/api/internal/runtime/{action}",
    data=b"",
    method="POST",
    headers={"X-Deploy-Control-Secret": secret},
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.read().decode("utf-8", "ignore"))
PY
}

reload_caddy() {
    docker compose up -d caddy >/dev/null
    local attempts="${1:-30}"
    for _ in $(seq 1 "$attempts"); do
        if docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "ERROR: Timed out waiting for Caddy to accept a config reload."
    return 1
}

switch_traffic_to_color() {
    local color="$1"
    render_active_upstreams "$color"
    reload_caddy
}

check_host_ollama() {
    echo ">>> Checking Ollama on the host..."
    if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null; then
        echo "ERROR: Ollama is not reachable on the host at http://127.0.0.1:11434."
        echo "  Start Ollama and make sure it is serving before deploying."
        exit 1
    fi
}

verify_backend_ollama() {
    local service="$1"
    echo ">>> Verifying ${service} can reach Ollama..."
    if ! docker compose exec -T "$service" python3 - <<'PY'
import json
import sys
import urllib.request

from config import (
    AUTO_TRIAGE_MODEL,
    AZURE_ALERT_RULE_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_FAST_MODEL,
    OLLAMA_MODEL,
    REPORT_AI_SUMMARY_MODEL,
    TECHNICIAN_SCORE_MODEL,
)

base = OLLAMA_BASE_URL.rstrip("/")
models_to_check = {
    candidate.strip()
    for candidate in (
        OLLAMA_MODEL,
        OLLAMA_FAST_MODEL,
        AUTO_TRIAGE_MODEL,
        TECHNICIAN_SCORE_MODEL,
        AZURE_ALERT_RULE_MODEL,
        REPORT_AI_SUMMARY_MODEL,
    )
    if candidate and candidate.strip()
}
if not base:
    print("OLLAMA_BASE_URL is not set in the backend container.")
    sys.exit(1)
if not models_to_check:
    print("No Ollama models are configured in the backend container.")
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

models = {entry.get("model") or entry.get("name") for entry in payload.get("models") or []}
missing = sorted(model for model in models_to_check if model not in models)
if missing:
    print(f"Configured Ollama model(s) missing on the host: {missing}")
    sys.exit(1)
PY
    then
        echo "ERROR: ${service} cannot reach Ollama."
        exit 1
    fi
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

start_services() {
    docker compose up -d "$@"
}

cleanup_legacy_single_services() {
    local service container_ids
    for service in backend frontend; do
        container_ids="$(docker ps -aq \
            --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
            --filter "label=com.docker.compose.service=${service}")"
        if [[ -n "$container_ids" ]]; then
            echo ">>> Removing legacy single-color container(s) for ${service}..."
            docker rm -f $container_ids >/dev/null || true
        fi
    done
}

prepare_runtime_state_for_bootstrap() {
    local service="$1"
    docker compose run --rm --no-deps -T "$service" python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

data_dir = Path(os.environ.get("DATA_DIR", "") or "/app/data")
db_path = data_dir / "runtime_state.db"
db_path.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(str(db_path))
try:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_leader_state (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            desired_leader_color TEXT NOT NULL DEFAULT '',
            lease_owner_color TEXT NOT NULL DEFAULT '',
            lease_expires_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO runtime_leader_state (
            singleton_id, desired_leader_color, lease_owner_color, lease_expires_at, updated_at
        ) VALUES (1, 'legacy', '', '', datetime('now'))
        ON CONFLICT(singleton_id) DO UPDATE SET
            desired_leader_color = 'legacy',
            lease_owner_color = '',
            lease_expires_at = '',
            updated_at = datetime('now')
        """
    )
    conn.commit()
finally:
    conn.close()
PY
}

rollback_to_previous_color() {
    local previous_color="$1"
    local failed_color="$2"
    if [[ -n "$previous_color" ]]; then
        echo ">>> Rolling back traffic to ${previous_color}..."
        post_internal_runtime "$(backend_service_for_color "$previous_color")" promote >/dev/null || true
        post_internal_runtime "$(backend_service_for_color "$failed_color")" demote >/dev/null || true
        wait_for_backend_role "$(backend_service_for_color "$previous_color")" leader 60 || true
        switch_traffic_to_color "$previous_color"
        return 0
    fi
    if legacy_service_is_running backend && legacy_service_is_running frontend; then
        echo ">>> Rolling back traffic to legacy single-color services..."
        render_legacy_upstreams
        reload_caddy
    fi
}

ensure_state_dir

ACTIVE_COLOR=""
TARGET_COLOR=""
BOOTSTRAP_DEPLOY=0
if [[ -f "$ACTIVE_COLOR_FILE" ]]; then
    ACTIVE_COLOR="$(read_active_color)"
    TARGET_COLOR="$(other_color "$ACTIVE_COLOR")"
else
    BOOTSTRAP_DEPLOY=1
    TARGET_COLOR="blue"
fi

TARGET_BACKEND_SERVICE="$(backend_service_for_color "$TARGET_COLOR")"
TARGET_FRONTEND_SERVICE="$(frontend_service_for_color "$TARGET_COLOR")"
PREVIOUS_BACKEND_SERVICE=""
if [[ -n "$ACTIVE_COLOR" ]]; then
    PREVIOUS_BACKEND_SERVICE="$(backend_service_for_color "$ACTIVE_COLOR")"
fi

if [[ "$VERIFY_OLLAMA" == "1" ]]; then
    check_host_ollama
fi

if [[ "$CADDY_IMAGE_REQUIRED" == "1" ]]; then
    echo ">>> Building caddy image..."
    build_services caddy
fi

echo ">>> Building inactive app color (${TARGET_COLOR})..."
build_services "$TARGET_BACKEND_SERVICE" "$TARGET_FRONTEND_SERVICE"

if [[ "$BOOTSTRAP_DEPLOY" == "1" ]] && legacy_service_is_running backend; then
    echo ">>> Preparing runtime state for migration from the legacy single backend..."
    prepare_runtime_state_for_bootstrap "$TARGET_BACKEND_SERVICE"
fi

if [[ "$BOOTSTRAP_DEPLOY" == "1" ]] && legacy_service_is_running backend && legacy_service_is_running frontend; then
    echo ">>> Keeping Caddy pointed at legacy services until blue-green cutover succeeds..."
    render_legacy_upstreams
else
    ensure_active_upstreams_file
fi

echo ">>> Starting inactive app color (${TARGET_COLOR})..."
start_services "$TARGET_BACKEND_SERVICE" "$TARGET_FRONTEND_SERVICE"

if ! service_is_running caddy; then
    echo ">>> Starting Caddy..."
    start_services caddy
fi

wait_for_container_http "$TARGET_BACKEND_SERVICE" 8000 "/api/health" "${TARGET_BACKEND_SERVICE} API liveness"
verify_backend_ollama "$TARGET_BACKEND_SERVICE"

if [[ "$BOOTSTRAP_DEPLOY" == "0" ]]; then
    wait_for_backend_role "$TARGET_BACKEND_SERVICE" follower
fi

wait_for_container_http "$TARGET_FRONTEND_SERVICE" 80 "/" "${TARGET_FRONTEND_SERVICE} shell"

echo ">>> Promoting ${TARGET_BACKEND_SERVICE} to leader..."
post_internal_runtime "$TARGET_BACKEND_SERVICE" promote >/dev/null
if [[ -n "$PREVIOUS_BACKEND_SERVICE" ]]; then
    echo ">>> Handing leadership off from ${PREVIOUS_BACKEND_SERVICE}..."
    post_internal_runtime "$PREVIOUS_BACKEND_SERVICE" demote >/dev/null || true
elif [[ "$BOOTSTRAP_DEPLOY" == "1" ]] && legacy_service_is_running backend; then
    echo ">>> Legacy backend remains online until cutover completes."
fi
wait_for_backend_role "$TARGET_BACKEND_SERVICE" leader

echo ">>> Switching public traffic to ${TARGET_COLOR}..."
switch_traffic_to_color "$TARGET_COLOR"

if ! wait_for_public_https "/api/health" "API liveness after cutover" 60; then
    echo "ERROR: Public API health failed after cutover."
    rollback_to_previous_color "$ACTIVE_COLOR" "$TARGET_COLOR"
    exit 1
fi

if ! wait_for_public_https "/" "frontend shell after cutover" 60; then
    echo "ERROR: Public frontend failed after cutover."
    rollback_to_previous_color "$ACTIVE_COLOR" "$TARGET_COLOR"
    exit 1
fi

print_readiness

if [[ -n "$PREVIOUS_BACKEND_SERVICE" ]]; then
    echo ">>> Demoting previous backend color (${ACTIVE_COLOR}) to follower..."
    post_internal_runtime "$PREVIOUS_BACKEND_SERVICE" demote >/dev/null || true
fi

write_active_color "$TARGET_COLOR"
cleanup_legacy_single_services

mkdir -p "$STATE_DIR"
printf '%s\n' "$CURRENT_SHA" > "$STATE_FILE"

echo ""
echo "=== DEPLOYED SUCCESSFULLY ==="
echo "  Mode:                $MODE"
echo "  Active app color:    $TARGET_COLOR"
if [[ -n "$ACTIVE_COLOR" ]]; then
    echo "  Previous app color:  $ACTIVE_COLOR"
fi
echo "  Dashboard:           https://it-app.movedocs.com"
echo "  OasisDev:            https://oasisdev.movedocs.com"
echo "  Azure:               https://azure.movedocs.com"
echo "  Health:              https://it-app.movedocs.com/api/health"
echo "  Ready:               https://it-app.movedocs.com/api/health/ready"
echo ""
docker compose ps
