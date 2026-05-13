"""
Migrate all vector data from Milvus to pgvector.

Phases:
  A — Extract each Milvus collection to a JSONL checkpoint file.
  B — Load each checkpoint into pgvector (embeddings reused, no re-computation).
  C — Verify row counts match.

Usage:
    python scripts/migrate_milvus_to_pgvector.py            # full run
    python scripts/migrate_milvus_to_pgvector.py --phase a  # extract only
    python scripts/migrate_milvus_to_pgvector.py --phase b  # load only (checkpoints must exist)
    python scripts/migrate_milvus_to_pgvector.py --phase c  # verify only
    python scripts/migrate_milvus_to_pgvector.py --collections pyegeria,egeria_java
    python scripts/migrate_milvus_to_pgvector.py --drop-existing  # recreate pg tables
"""

import argparse
import json
import sys
import time
from pathlib import Path

from loguru import logger
from pymilvus import Collection, connections, utility

# ---------------------------------------------------------------------------
# Allow running from repo root without installing the package
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.collection_config import get_enabled_collections
from advisor.config import settings
from advisor.vector_store_pg import PgVectorStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKPOINT_DIR = Path("data/migration")

# Milvus query batch size — stay well below the 16,384 hard limit
EXTRACT_BATCH = 1000

# pgvector insert batch size
INSERT_BATCH = 500

# Extra scalar fields present in specific Milvus collections
_EXTRA_FIELDS: dict[str, list[str]] = {
    "pyegeria": ["element_type", "class_name", "method_name", "module_path", "is_async", "is_private"],
    # cli_commands is the legacy Milvus name; pyegeria_cli is the config name
    "pyegeria_cli": ["main_command", "subcommand", "full_command"],
    "cli_commands": ["main_command", "subcommand", "full_command"],
}

# Map Milvus collection name → pgvector table name.
# The only rename needed is pyegeria_drE → pyegeria_dre (avoid case-sensitive quoting).
_PG_NAME: dict[str, str] = {
    "pyegeria_drE": "pyegeria_dre",
    "cli_commands": "pyegeria_cli",
}


def pg_table_name(milvus_name: str) -> str:
    return _PG_NAME.get(milvus_name, milvus_name)


# ---------------------------------------------------------------------------
# Progress / checkpoint helpers
# ---------------------------------------------------------------------------

PROGRESS_FILE = CHECKPOINT_DIR / "progress.json"


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {}


def _save_progress(progress: dict) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def _jsonl_path(collection_name: str) -> Path:
    return CHECKPOINT_DIR / f"{collection_name}.jsonl"


# ---------------------------------------------------------------------------
# Phase A — Extract from Milvus
# ---------------------------------------------------------------------------

def _connect_milvus() -> None:
    logger.info(f"Connecting to Milvus at {settings.milvus_host}:{settings.milvus_port}")
    connections.connect(
        alias="default",
        host=settings.milvus_host,
        port=str(settings.milvus_port),
    )
    logger.info(f"✓ Connected to Milvus v{utility.get_server_version()}")


def _extract_collection(milvus_name: str) -> int:
    """
    Extract all records from one Milvus collection into a JSONL checkpoint.
    Returns the number of records written.
    """
    out_path = _jsonl_path(milvus_name)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    if not utility.has_collection(milvus_name):
        logger.warning(f"  Milvus collection not found: {milvus_name} — skipping")
        return 0

    collection = Collection(milvus_name)
    collection.load()

    total_in_milvus = collection.num_entities
    logger.info(f"  {milvus_name}: {total_in_milvus} entities in Milvus")

    # Introspect actual schema — only request fields that exist in this collection
    base_fields = {"id", "text", "metadata", "embedding"}
    schema_fields = {f.name for f in collection.schema.fields}
    known_extras = set(_EXTRA_FIELDS.get(milvus_name, []))
    extra_fields = [f for f in _EXTRA_FIELDS.get(milvus_name, []) if f in schema_fields]
    if known_extras - schema_fields:
        logger.warning(
            f"  {milvus_name}: scalar fields not in schema (will be skipped): "
            f"{sorted(known_extras - schema_fields)}"
        )
    output_fields = [f for f in ["id", "text", "metadata", "embedding"] if f in schema_fields]
    output_fields += extra_fields

    records_written = 0

    # Use QueryIterator (Milvus 2.3+) to avoid the offset+limit ≤ 16384 hard limit.
    iterator = collection.query_iterator(
        expr="id != ''",
        output_fields=output_fields,
        batch_size=EXTRACT_BATCH,
    )

    with open(out_path, "w") as f:
        while True:
            batch = iterator.next()
            if not batch:
                break

            for record in batch:
                embedding = record.get("embedding", [])
                if hasattr(embedding, "tolist"):
                    embedding = embedding.tolist()

                row = {
                    "id": record["id"],
                    "embedding": embedding,
                    "text": record.get("text", ""),
                    "metadata": record.get("metadata") or {},
                }
                for col in extra_fields:
                    row[col] = record.get(col, "")

                f.write(json.dumps(row) + "\n")
                records_written += 1

            logger.debug(f"    extracted {records_written}/{total_in_milvus}")

    iterator.close()

    logger.info(f"  ✓ Extracted {records_written} records → {out_path}")
    return records_written


def phase_a(collection_names: list[str]) -> dict[str, int]:
    logger.info("=" * 60)
    logger.info("Phase A — Extracting from Milvus")
    logger.info("=" * 60)
    _connect_milvus()

    progress = _load_progress()
    counts: dict[str, int] = {}

    for name in collection_names:
        if progress.get(f"extracted_{name}"):
            path = _jsonl_path(name)
            # Count lines in existing checkpoint
            n = sum(1 for _ in open(path)) if path.exists() else 0
            logger.info(f"  {name}: already extracted ({n} records) — skipping")
            counts[name] = n
            continue

        logger.info(f"  Extracting {name} …")
        t0 = time.time()
        n = _extract_collection(name)
        elapsed = time.time() - t0
        counts[name] = n
        progress[f"extracted_{name}"] = True
        _save_progress(progress)
        logger.info(f"  {name}: done in {elapsed:.1f}s")

    connections.disconnect("default")
    logger.info("Phase A complete\n")
    return counts


# ---------------------------------------------------------------------------
# Phase B — Load into pgvector
# ---------------------------------------------------------------------------

def _load_collection(pg: PgVectorStore, milvus_name: str, drop_existing: bool) -> int:
    """
    Read a JSONL checkpoint and insert into pgvector.
    Returns the number of rows inserted.
    """
    in_path = _jsonl_path(milvus_name)
    table_name = pg_table_name(milvus_name)

    if not in_path.exists():
        logger.warning(f"  Checkpoint not found for {milvus_name}: {in_path} — skipping")
        return 0

    # Count total lines for progress reporting
    total_lines = sum(1 for _ in open(in_path))
    logger.info(f"  {milvus_name} → {table_name}: {total_lines} records")

    pg.create_collection(table_name, drop_if_exists=drop_existing)
    # Index created after bulk insert (avoids incremental maintenance during load)

    extra_fields = _EXTRA_FIELDS.get(milvus_name, _EXTRA_FIELDS.get(table_name, []))

    texts: list[str] = []
    embeddings: list[list[float]] = []
    ids: list[str] = []
    metadata_list: list[dict] = []

    total_inserted = 0
    batch_num = 0

    with open(in_path) as f:
        for line in f:
            row = json.loads(line)

            texts.append(row["text"])
            embeddings.append(row["embedding"])
            ids.append(row["id"])

            # Merge extra scalar fields back into metadata dict so
            # insert_with_embeddings can pick them up via _EXTRA_COLUMNS
            meta = dict(row.get("metadata") or {})
            for col in extra_fields:
                if col in row:
                    meta[col] = row[col]
            metadata_list.append(meta)

            if len(texts) >= INSERT_BATCH:
                n = pg.insert_with_embeddings(
                    table_name, texts, embeddings, ids, metadata_list,
                    batch_size=INSERT_BATCH,
                )
                total_inserted += n
                batch_num += 1
                logger.debug(f"    batch {batch_num}: {total_inserted}/{total_lines} inserted")
                texts, embeddings, ids, metadata_list = [], [], [], []

    # Flush remaining
    if texts:
        n = pg.insert_with_embeddings(
            table_name, texts, embeddings, ids, metadata_list,
            batch_size=INSERT_BATCH,
        )
        total_inserted += n

    # Build HNSW index after bulk load
    pg.create_index(table_name)

    logger.info(f"  ✓ Loaded {total_inserted} rows into {table_name}")
    return total_inserted


def phase_b(collection_names: list[str], drop_existing: bool) -> dict[str, int]:
    logger.info("=" * 60)
    logger.info("Phase B — Loading into pgvector")
    logger.info("=" * 60)

    pg = PgVectorStore()
    pg.connect()

    progress = _load_progress()
    counts: dict[str, int] = {}

    for name in collection_names:
        table_name = pg_table_name(name)
        progress_key = f"loaded_{table_name}"

        if not drop_existing and progress.get(progress_key):
            n = pg.get_collection_stats(table_name)["num_entities"]
            logger.info(f"  {name} → {table_name}: already loaded ({n} rows) — skipping")
            counts[name] = n
            continue

        logger.info(f"  Loading {name} → {table_name} …")
        t0 = time.time()
        n = _load_collection(pg, name, drop_existing=drop_existing)
        elapsed = time.time() - t0
        counts[name] = n
        progress[progress_key] = True
        _save_progress(progress)
        logger.info(f"  {name}: done in {elapsed:.1f}s")

    pg.disconnect()
    logger.info("Phase B complete\n")
    return counts


# ---------------------------------------------------------------------------
# Phase C — Verify
# ---------------------------------------------------------------------------

def phase_c(collection_names: list[str]) -> bool:
    logger.info("=" * 60)
    logger.info("Phase C — Verifying row counts")
    logger.info("=" * 60)

    _connect_milvus()

    pg = PgVectorStore()
    pg.connect()

    all_ok = True
    rows = []

    for name in collection_names:
        table_name = pg_table_name(name)

        # Ground truth: JSONL checkpoint line count (what was actually extracted from Milvus).
        # Milvus num_entities includes deleted-but-not-compacted tombstones and can be higher
        # than the real live record count, so we use the checkpoint as the authoritative source.
        jsonl_path = _jsonl_path(name)
        if jsonl_path.exists():
            extracted_count: int | str = sum(1 for _ in open(jsonl_path))
        elif utility.has_collection(name):
            # Fall back to Milvus num_entities if no checkpoint (e.g., --phase c only)
            col = Collection(name)
            extracted_count = col.num_entities
        else:
            extracted_count = "N/A"

        # pgvector count
        pg_count: int | str
        try:
            pg_count = pg.get_collection_stats(table_name)["num_entities"]
        except Exception:
            pg_count = "N/A (table missing)"

        match = (
            isinstance(extracted_count, int)
            and isinstance(pg_count, int)
            and extracted_count == pg_count
        )
        status = "✓" if match else "✗"
        if not match:
            all_ok = False

        rows.append((status, name, table_name, extracted_count, pg_count))

    connections.disconnect("default")
    pg.disconnect()

    # Print table
    print()
    print(f"  {'':2}  {'Milvus collection':<22}  {'PG table':<22}  {'Extracted':>9}  {'pgvector':>8}")
    print(f"  {'':2}  {'-'*22}  {'-'*22}  {'-'*9}  {'-'*8}")
    for status, mname, tname, mc, pc in rows:
        print(f"  {status}   {mname:<22}  {tname:<22}  {str(mc):>9}  {str(pc):>8}")
    print()

    if all_ok:
        logger.info("✓ All collections match (extracted vs pgvector)")
    else:
        logger.error("✗ Count mismatches detected — see table above")

    logger.info("Phase C complete\n")
    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _default_collection_names() -> list[str]:
    """Return Milvus-side names for all enabled collections."""
    names = []
    for col in get_enabled_collections():
        # Map config name back to the Milvus name if it differs
        # (currently only cli_commands vs pyegeria_cli matters if the Milvus
        #  collection was originally indexed as cli_commands)
        names.append(col.name)
    return names


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Egeria Advisor vector data from Milvus to pgvector"
    )
    parser.add_argument(
        "--phase",
        choices=["a", "b", "c", "all"],
        default="all",
        help="Which phase(s) to run (default: all)",
    )
    parser.add_argument(
        "--collections",
        default=None,
        help="Comma-separated list of Milvus collection names (default: all enabled)",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop and recreate pgvector tables before loading",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Ignore checkpoints and rerun from scratch",
    )
    args = parser.parse_args()

    if args.reset_progress and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        logger.info("Progress reset")

    if args.collections:
        collection_names = [c.strip() for c in args.collections.split(",")]
    else:
        collection_names = _default_collection_names()

    logger.info(f"Collections to migrate: {collection_names}")

    phases = args.phase if args.phase != "all" else "abc"

    if "a" in phases:
        phase_a(collection_names)

    if "b" in phases:
        phase_b(collection_names, drop_existing=args.drop_existing)

    if "c" in phases:
        ok = phase_c(collection_names)
        if not ok:
            sys.exit(1)

    logger.info("Migration complete")


if __name__ == "__main__":
    main()
