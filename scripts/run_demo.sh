#!/usr/bin/env bash
# One command to run the PageIndex demo: database, deps, index, backend, frontend.
#
#   ./scripts/run_demo.sh            start everything (Ctrl+C stops it all)
#   ./scripts/run_demo.sh --check    also ask one live question first, as a smoke test
#
# Env overrides:
#   PAGEINDEX_DOCS   folder to index if the collection is empty
#                    (default: your Literature Review folder)
#   COLLECTION       collection name (default: litreview)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COLLECTION="${COLLECTION:-litreview}"
DOCS="${PAGEINDEX_DOCS:-/mnt/c/Users/USER/OneDrive/Desktop/Birmingham/Dissertation/Literature Review}"
LOGS="$ROOT/logs"
DB_CONTAINER=pageindex_pg
mkdir -p "$LOGS"

step() { printf '\n\033[38;5;208m▸ %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '  ✓ %s\n' "$*"; }

# ---------------------------------------------------------------- preflight
step "Preflight"
command -v uv >/dev/null     || fail "uv not found"
command -v npm >/dev/null    || fail "npm not found"
command -v docker >/dev/null || fail "docker not found. Start Docker Desktop and enable WSL integration"
[ -e .env ] || fail ".env missing. Link it:  ln -s /home/anshul/projects/agentic_rag/.env $ROOT/.env"
uv run python -c "
from dotenv import load_dotenv; import os, sys; load_dotenv()
missing = [k for k in ('OPENROUTER_KEY', 'SECRET_KEY') if not os.getenv(k)]
sys.exit(f'missing in .env: {missing}' if missing else 0)" || fail "required keys missing from .env"
ok ".env has OPENROUTER_KEY and SECRET_KEY (values not shown)"
for port in 7777 3000; do
  if ss -ltn 2>/dev/null | grep -q ":$port "; then
    fail "port $port is already in use (is the main app running?). Stop it and retry"
  fi
done
ok "ports 7777 and 3000 are free"

# ---------------------------------------------------------------- database
step "Database ($DB_CONTAINER on 127.0.0.1:5534)"
if docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  ok "already running"
elif docker ps -a --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  docker start "$DB_CONTAINER" >/dev/null && ok "started existing container"
else
  docker run -d --name "$DB_CONTAINER" --restart unless-stopped \
    -e POSTGRES_USER=pageindex -e POSTGRES_PASSWORD=pageindex -e POSTGRES_DB=pageindex \
    -p 127.0.0.1:5534:5432 -v pageindex_pgdata:/var/lib/postgresql/data \
    --health-cmd "pg_isready -U pageindex" --health-interval 2s \
    pgvector/pgvector:pg17 >/dev/null && ok "created new container"
fi
for _ in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER")" = healthy ] && break; sleep 1
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER")" = healthy ] || fail "database not healthy"
ok "healthy"

# ---------------------------------------------------------------- dependencies
step "Dependencies"
uv sync -q && ok "python (uv sync)"
if [ ! -d UI-Iluminati/node_modules ]; then
  (cd UI-Iluminati && npm ci --no-audit --no-fund --loglevel=error) && ok "frontend (npm ci)"
else
  ok "frontend (node_modules present)"
fi

# ---------------------------------------------------------------- index
step "Index (collection '$COLLECTION')"
n_docs=$(uv run python -c "
from pageindex_rag.store import Store; print(len(Store().list_documents('$COLLECTION')))")
if [ "$n_docs" -gt 0 ]; then
  ok "$n_docs documents already indexed"
else
  [ -d "$DOCS" ] || fail "collection empty and PAGEINDEX_DOCS folder not found: $DOCS"
  echo "  indexing $DOCS (first run: ~3 min, ~\$0.20 of LLM summaries)…"
  uv run python -m pageindex_rag.cli index --collection "$COLLECTION" "$DOCS" 2>&1 \
    | grep -aE "^(parse|title|skip|FAIL|LLM)" || true
fi
PYTHONPATH=. uv run python bench/make_fixtures.py >/dev/null 2>&1 && ok "replay fixtures ready" || true

# ---------------------------------------------------------------- optional smoke test
if [ "${1:-}" = "--check" ]; then
  step "Live smoke test (one question, ~\$0.04)"
  uv run python -m pageindex_rag.cli ask --collection "$COLLECTION" \
    "How many fraudulent transactions does the PaySim dataset contain in the K-SMOTEENN paper?" 2>&1 | tail -4
fi

# ---------------------------------------------------------------- servers
step "Starting servers (logs in logs/)"
pids=()
cleanup() {
  printf '\nStopping…\n'
  for pid in "${pids[@]}"; do
    pkill -TERM -P "$pid" 2>/dev/null || true   # children (uv -> python, npm -> next)
    kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "Stopped. (Database container keeps running: docker stop $DB_CONTAINER)"
}
trap cleanup EXIT INT TERM

uv run agent-api.py > "$LOGS/backend.log" 2>&1 & pids+=($!)
(cd UI-Iluminati && npm run dev -- -p 3000) > "$LOGS/frontend.log" 2>&1 & pids+=($!)

for _ in $(seq 1 90); do curl -sf localhost:7777/health >/dev/null && break; sleep 1; done
curl -sf localhost:7777/health >/dev/null || { tail -20 "$LOGS/backend.log"; fail "backend did not start"; }
ok "backend  http://localhost:7777"
for _ in $(seq 1 90); do curl -s -o /dev/null -w '%{http_code}' localhost:3000/login | grep -q 200 && break; sleep 1; done
ok "frontend http://localhost:3000"

cat <<EOF

  ┌──────────────────────────────────────────────────────────────────┐
  │  Open  http://localhost:3000/pageindex                           │
  │  First time: sign up at /signup (this worktree has its own users)│
  │  Test questions:  docs/TEST_QUESTIONS.md                         │
  │  Replay dropdown: saved runs, no LLM cost (good for demos)       │
  │  Logs: logs/backend.log, logs/frontend.log  ·  Ctrl+C to stop    │
  └──────────────────────────────────────────────────────────────────┘
EOF
wait
