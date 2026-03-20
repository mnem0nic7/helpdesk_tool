#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

blocked_paths=(
  ".env"
  "backend/.env"
  "*.doc"
  "*.docx"
  "*.xls"
  "*.xlsx"
  "*.xlsm"
  "*.ppt"
  "*.pptx"
  "*.zip"
  "*.7z"
  "*.db"
  "*.sqlite"
  "*.sqlite3"
  "*.pem"
  "*.pfx"
  "*.key"
  "*.msg"
)

mapfile -d '' tracked < <(git ls-files -z -- "${blocked_paths[@]}")

if (( ${#tracked[@]} )); then
    echo "ERROR: Blocked tracked artifacts detected:"
    for path in "${tracked[@]}"; do
        [[ -n "$path" ]] && printf '  - %s\n' "$path"
    done
    echo "Move operational/binary/secret material out of git before releasing."
    exit 1
fi

echo "Repo hygiene check passed."
