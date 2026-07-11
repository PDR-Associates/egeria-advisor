#!/bin/bash
# Full reset of the RAG data pipeline: source repos + pgvector store.
#
# Brings data/repos/, the pgvector tables, and config/advisor.yaml back into a
# single consistent state by re-cloning every source repo from scratch and
# re-ingesting every collection from that fresh snapshot. Use this whenever
# the downloaded repos, the vector store, and the config have drifted apart
# (e.g. a repo directory was deleted after ingestion, or only some
# collections were re-ingested after a repo update).
#
# Usage:
#   scripts/full_reset.sh          # prompts for confirmation
#   scripts/full_reset.sh --yes    # skip confirmation (for automation)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

REPOS_DIR="data/repos"
REPOS=("egeria-python" "egeria" "egeria-docs" "egeria-workspaces")

SKIP_CONFIRM=false
for arg in "$@"; do
    case "$arg" in
        --yes|-y) SKIP_CONFIRM=true ;;
    esac
done

echo "=========================================="
echo "Egeria Advisor — Full Data Pipeline Reset"
echo "=========================================="
echo "This will:"
echo "  1. Delete and re-clone: ${REPOS[*]}"
echo "  2. Drop and re-ingest all enabled pgvector collections"
echo ""
echo "This does NOT touch MLflow runs, query cache, or feedback data."
echo ""

if [ "$SKIP_CONFIRM" != true ]; then
    read -r -p "Proceed? [y/N] " reply
    case "$reply" in
        [yY][eE][sS]|[yY]) ;;
        *) echo "Aborted."; exit 1 ;;
    esac
fi

if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

echo ""
echo "--- Step 1/3: Removing existing checkouts ---"
for repo in "${REPOS[@]}"; do
    repo_path="$REPOS_DIR/$repo"
    if [ -d "$repo_path" ]; then
        echo "Removing $repo_path"
        rm -rf "$repo_path"
    fi
done

echo ""
echo "--- Step 2/3: Cloning all repos fresh ---"
python scripts/clone_repos.py --phase all

echo ""
echo "--- Step 3/3: Re-ingesting all enabled collections ---"
python scripts/ingest_collections.py --phase all --force

echo ""
echo "=========================================="
echo "Verifying pgvector row counts"
echo "=========================================="
python - <<'PYEOF'
from advisor.vector_store import get_vector_store
from advisor.collection_config import get_enabled_collections

store = get_vector_store()
store.connect()
conn = store._get_conn()
try:
    with conn.cursor() as cur:
        for c in get_enabled_collections():
            table = store._table(c.name)
            cur.execute(f'SELECT count(*) FROM "{table}"')
            print(f"{c.name}: {cur.fetchone()[0]} rows")
finally:
    store._put_conn(conn)
PYEOF

echo ""
echo "Reset complete."
