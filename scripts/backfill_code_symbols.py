"""Backfill the code_symbols SQLite table from already-ingested Python collections.

Run this once after upgrading to populate the symbol table for existing collections
without a full re-ingest into pgvector.

Usage:
    python scripts/backfill_code_symbols.py [--collection pyegeria]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from advisor.code_symbol_store import get_symbol_store
from advisor.data_prep.code_parser import CodeParser
from advisor.collection_config import get_enabled_collections
from advisor.config import settings

PYTHON_EXTENSIONS = {".py"}

_COLLECTION_SOURCE: dict[str, Path] = {
    "pyegeria":     Path(settings.advisor_data_path) / "repos" / "egeria-python",
    "pyegeria_cli": Path(settings.advisor_data_path) / "repos" / "egeria-python",
    "pyegeria_drE": Path(settings.advisor_data_path) / "repos" / "egeria-python",
}


def _source_root(collection_name: str) -> Path | None:
    if collection_name in _COLLECTION_SOURCE:
        p = _COLLECTION_SOURCE[collection_name]
        if p.exists():
            return p
    # Try to find via collection config source_paths
    from advisor.collection_config import get_collection
    meta = get_collection(collection_name)
    if not meta:
        return None
    for rel in meta.source_paths or []:
        candidate = Path(settings.advisor_data_path) / rel
        if candidate.exists():
            return candidate
    return None


def backfill(collection_name: str) -> int:
    root = _source_root(collection_name)
    if root is None:
        logger.warning(f"No source root found for '{collection_name}' — skipping")
        return 0

    logger.info(f"Backfilling '{collection_name}' from {root}")
    store = get_symbol_store()
    store.clear_collection(collection_name)

    parser = CodeParser()
    all_elements = []
    for py_file in root.rglob("*.py"):
        if any(p in py_file.parts for p in ("__pycache__", "deprecated", ".git", ".venv")):
            continue
        elements = parser.parse_file(py_file)
        all_elements.extend(elements)

    count = store.upsert_symbols(collection_name, all_elements)
    logger.info(f"  → {count} symbols written for '{collection_name}'")
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill code_symbols table from source repos")
    ap.add_argument("--collection", default=None, help="Single collection name (default: all Python)")
    args = ap.parse_args()

    if args.collection:
        targets = [args.collection]
    else:
        all_cols = get_enabled_collections()
        targets = [c.name for c in all_cols if c.language.value == "python"]

    total = 0
    for col in targets:
        total += backfill(col)

    logger.info(f"Done. {total} total symbols across {len(targets)} collection(s).")
    summary = get_symbol_store().collection_summary()
    for col, data in sorted(summary.items()):
        print(
            f"  {col}: {data.get('classes', 0)} classes · "
            f"{data.get('methods', 0)} methods · "
            f"{data.get('functions', 0)} functions"
        )


if __name__ == "__main__":
    main()
