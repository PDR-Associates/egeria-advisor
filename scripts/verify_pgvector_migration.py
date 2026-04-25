"""
Post-migration verification for the Milvus → pgvector migration.

Checks:
  1. Row counts match between Milvus and pgvector for each collection.
  2. Sample search results are consistent (same top-1 id from both backends).
  3. Score range is valid (0 < score ≤ 1).

Usage:
    python scripts/verify_pgvector_migration.py
    python scripts/verify_pgvector_migration.py --collections pyegeria,egeria_java
    python scripts/verify_pgvector_migration.py --no-search   # counts only
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.collection_config import get_enabled_collections
from advisor.config import settings
from advisor.vector_store import MilvusVectorStore
from advisor.vector_store_pg import PgVectorStore

# Five fixed queries — diverse enough to exercise different collections
SAMPLE_QUERIES = [
    "What is a glossary term in Egeria?",
    "How do I create an asset using pyegeria?",
    "hey_egeria CLI commands for governance",
    "Egeria OMAS access service Java implementation",
    "Dr. Egeria markdown commands for creating a data product",
]

_PG_NAME: dict[str, str] = {
    "pyegeria_drE": "pyegeria_dre",
    "cli_commands": "pyegeria_cli",
}


def pg_table_name(milvus_name: str) -> str:
    return _PG_NAME.get(milvus_name, milvus_name)


def verify(collection_names: list[str], run_search: bool) -> bool:
    milvus = MilvusVectorStore()
    pg = PgVectorStore()

    try:
        milvus.connect()
        pg.connect()
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return False

    all_ok = True
    count_rows = []
    search_rows = []

    for name in collection_names:
        table = pg_table_name(name)
        logger.info(f"Verifying {name} → {table}")

        # --- Count check ---
        try:
            m_stats = milvus.get_collection_stats(name)
            m_count = m_stats["num_entities"]
        except Exception as e:
            logger.warning(f"  Milvus count failed for {name}: {e}")
            m_count = None

        try:
            p_stats = pg.get_collection_stats(table)
            p_count = p_stats["num_entities"]
        except Exception as e:
            logger.warning(f"  pgvector count failed for {table}: {e}")
            p_count = None

        if m_count is not None and p_count is not None:
            match = m_count == p_count
            status = "✓" if match else "✗"
            if not match:
                all_ok = False
        else:
            status = "?"
            all_ok = False

        count_rows.append((status, name, table, m_count, p_count))

        # --- Search consistency check ---
        if run_search and m_count and p_count:
            mismatches = 0
            for query in SAMPLE_QUERIES:
                try:
                    m_results = milvus.search(name, query_text=query, top_k=1)
                    p_results = pg.search(table, query_text=query, top_k=1)
                except Exception as e:
                    logger.warning(f"  Search error for {name} query={query!r}: {e}")
                    continue

                if not m_results or not p_results:
                    continue

                m_top = m_results[0]
                p_top = p_results[0]

                id_match = m_top.id == p_top.id
                score_ok = 0 < p_top.score <= 1.0

                if not id_match:
                    mismatches += 1
                    logger.debug(
                        f"  top-1 mismatch: milvus={m_top.id!r} ({m_top.score:.3f}) "
                        f"pg={p_top.id!r} ({p_top.score:.3f})"
                    )
                if not score_ok:
                    logger.warning(f"  invalid score {p_top.score} for query {query!r}")
                    all_ok = False

            search_rows.append((name, table, len(SAMPLE_QUERIES), mismatches))

    milvus.disconnect()
    pg.disconnect()

    # --- Print count table ---
    print()
    print(f"  {'':2}  {'Milvus collection':<22}  {'PG table':<22}  {'Milvus':>8}  {'pgvector':>8}")
    print(f"  {'':2}  {'-'*22}  {'-'*22}  {'-'*8}  {'-'*8}")
    for status, mname, tname, mc, pc in count_rows:
        print(f"  {status}   {mname:<22}  {tname:<22}  {str(mc):>8}  {str(pc):>8}")
    print()

    # --- Print search table ---
    if run_search and search_rows:
        print(f"  {'Collection':<24}  {'Queries':>7}  {'Top-1 mismatches':>16}")
        print(f"  {'-'*24}  {'-'*7}  {'-'*16}")
        for mname, tname, total, mismatches in search_rows:
            sym = "✓" if mismatches == 0 else "⚠"
            print(f"  {sym} {mname:<22}  {total:>7}  {mismatches:>16}")
        print()

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Milvus → pgvector migration correctness"
    )
    parser.add_argument(
        "--collections",
        default=None,
        help="Comma-separated Milvus collection names (default: all enabled)",
    )
    parser.add_argument(
        "--no-search",
        action="store_true",
        help="Skip search consistency check (counts only)",
    )
    args = parser.parse_args()

    if args.collections:
        collection_names = [c.strip() for c in args.collections.split(",")]
    else:
        collection_names = [c.name for c in get_enabled_collections()]

    ok = verify(collection_names, run_search=not args.no_search)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
