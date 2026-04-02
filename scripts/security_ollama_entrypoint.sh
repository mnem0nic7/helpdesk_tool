#!/bin/sh
set -eu

READY_FILE="/tmp/security-ollama-ready"
PRIMARY_MODEL="${SECURITY_OLLAMA_PRIMARY_MODEL:-qwen3.5:4b}"
FALLBACK_MODEL="${SECURITY_OLLAMA_FALLBACK_MODEL:-nemotron-3-nano:4b}"
CLIENT_HOST="http://127.0.0.1:11434"

rm -f "$READY_FILE"

OLLAMA_HOST="0.0.0.0:11434" ollama serve &
OLLAMA_PID="$!"

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

wait_for_server() {
  for _ in $(seq 1 120); do
    if OLLAMA_HOST="$CLIENT_HOST" ollama list >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "security_ollama failed to start within 120 seconds" >&2
  return 1
}

ensure_model() {
  model_id="$1"
  if [ -z "$model_id" ]; then
    return 0
  fi
  if OLLAMA_HOST="$CLIENT_HOST" ollama show "$model_id" >/dev/null 2>&1; then
    return 0
  fi
  OLLAMA_HOST="$CLIENT_HOST" ollama pull "$model_id"
}

wait_for_server
ensure_model "$PRIMARY_MODEL"
if [ "$FALLBACK_MODEL" != "$PRIMARY_MODEL" ]; then
  ensure_model "$FALLBACK_MODEL"
fi
touch "$READY_FILE"

wait "$OLLAMA_PID"
