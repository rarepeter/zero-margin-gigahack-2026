#!/usr/bin/env sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker Desktop is required. Install and start it before running this check.' >&2
  exit 1
fi

docker compose up -d --pull never
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8025/readyz >/dev/null
docker compose ps

printf '%s\n' 'Mailpit is ready at http://127.0.0.1:8025 and accepts SMTP on 127.0.0.1:1025.'
