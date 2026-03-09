#!/usr/bin/env python3
"""
Simple script to re-ingest PyEgeria collection with scalar fields.
Uses the existing code_elements.json cache.
"""

import sys
import json
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.vector_store import VectorStoreManager
from pymilvus import utility


def main():
    """Re-ingest pyegeria collection."""
    
    logger.info("=" * 80)
    logger.info("RE-INGESTING PYEGERIA WITH SCALAR FIELDS")
    logger.info("=" * 80)
    
    # Initialize
    vs = VectorStoreManager()
    vs.connect()
    
    collection_name = "pyegeria"
    
    # Step 1: Drop and recreate
    if utility.has_collection(collection_name):
        logger.warning(f"Dropping {collection_name}...")
        utility.drop_collection(collection_name)
    
    logger.info(f"Creating {collection_name} with scalar fields...")
    vs.create_collection(collection_name, drop_if_exists=False)
    vs.create_index(collection_name)
    logger.info("✓ Collection created with scalar fields")
    
    # Step 2: Load cached data
    cache_file = Path("cache/code_elements.json")
    if not cache_file.exists():
        logger.error(f"Cache not found: {cache_file}")
        logger.error("Run: python -m advisor.data_prep.pipeline")
        return 1
    
    logger.info(f"Loading from: {cache_file}")
    with open(cache_file) as f:
        code_elements = json.load(f)
    
    logger.info(f"Loaded {len(code_elements)} code elements")
    
    # Step 3: Prepare data
    texts = []
    ids = []
    metadata_list = []
    
    for i, elem in enumerate(code_elements):
        # Create searchable text
        text_parts = [
            f"Name: {elem.get('name', '')}",
            f"Type: {elem.get('type', '')}",
        ]
        
        if elem.get('docstring'):
            text_parts.append(f"Documentation: {elem['docstring']}")
        
        if elem.get('signature'):
            text_parts.append(f"Signature: {elem['signature']}")
        
        if elem.get('code'):
            text_parts.append(f"Code: {elem['code'][:500]}")
        
        texts.append("\n".join(text_parts))
        ids.append(f"pyegeria_{i}_{elem.get('name', 'unknown')}")
        
        # Prepare metadata with scalar fields
        meta = {
            "element_type": elem.get('type', ''),
            "class_name": elem.get('class_name', ''),
            "method_name": elem.get('name', '') if elem.get('type') in ['method', 'function'] else '',
            "module_path": elem.get('module', ''),
            "is_async": elem.get('is_async', False),
            "is_private": elem.get('name', '').startswith('_') if elem.get('name') else False,
            # Keep full metadata in JSON field
            **elem
        }
        metadata_list.append(meta)
    
    # Step 4: Insert
    logger.info(f"Inserting {len(texts)} elements...")
    num_inserted = vs.insert_data(
        collection_name=collection_name,
        texts=texts,
        ids=ids,
        metadata=metadata_list,
        batch_size=500
    )
    
    logger.info(f"\n✓ Successfully inserted {num_inserted} elements")
    
    # Step 5: Verify
    from pymilvus import Collection
    coll = Collection(collection_name)
    logger.info(f"\nSchema fields:")
    for field in coll.schema.fields:
        logger.info(f"  - {field.name}: {field.dtype}")
    
    logger.info(f"\n✓ PyEgeria collection ready with metadata filtering!")
    return 0


if __name__ == "__main__":
    sys.exit(main())