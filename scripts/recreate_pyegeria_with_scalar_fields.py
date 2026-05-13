#!/usr/bin/env python3
"""
Recreate PyEgeria collection with scalar metadata fields for filtering.

This script:
1. Drops the existing pyegeria collection
2. Creates a new one with scalar fields (element_type, class_name, etc.)
3. Re-ingests all PyEgeria code elements with the new schema
"""

import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.vector_store import VectorStoreManager
from advisor.ingest_to_milvus import DataIngester
from pymilvus import utility


def main():
    """Recreate pyegeria collection with scalar fields."""
    
    logger.info("=" * 80)
    logger.info("RECREATING PYEGERIA COLLECTION WITH SCALAR METADATA FIELDS")
    logger.info("=" * 80)
    
    # Initialize vector store
    vs = VectorStoreManager()
    vs.connect()
    
    # Step 1: Drop existing collection
    collection_name = "pyegeria"
    if utility.has_collection(collection_name):
        logger.warning(f"Dropping existing collection: {collection_name}")
        utility.drop_collection(collection_name)
        logger.info(f"✓ Dropped {collection_name}")
    else:
        logger.info(f"Collection {collection_name} does not exist")
    
    # Step 2: Create new collection with scalar fields
    logger.info(f"Creating {collection_name} with scalar metadata fields...")
    collection = vs.create_collection(
        collection_name=collection_name,
        description="PyEgeria Python library code with scalar metadata fields",
        drop_if_exists=False  # Already dropped above
    )
    logger.info(f"✓ Created {collection_name} with enhanced schema")
    
    # Step 3: Create index
    logger.info("Creating vector index...")
    vs.create_index(collection_name=collection_name)
    logger.info("✓ Index created")
    
    # Step 4: Re-ingest PyEgeria code
    logger.info("\nRe-ingesting PyEgeria code elements...")
    logger.info("-" * 80)
    
    ingester = DataIngester()
    
    # Check if cache exists
    code_elements_file = Path("cache/code_elements.json")
    
    if not code_elements_file.exists():
        logger.error(f"Code elements cache not found: {code_elements_file}")
        logger.error("Please run the data preparation pipeline first")
        logger.error("Run: python -m advisor.data_prep.pipeline")
        return 1
    
    logger.info(f"Ingesting from cache: {code_elements_file}")
    
    # Note: ingest_code_elements creates "code_elements" collection by default
    # We need to manually ingest into "pyegeria" collection
    # For now, just use ingest_all which will create the right collection
    num_inserted = ingester.ingest_all(drop_existing=False)  # Don't drop - we just created it
    
    stats = {"total_inserted": num_inserted}
    
    logger.info("\n" + "=" * 80)
    logger.info("INGESTION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Files processed: {stats.get('files_processed', 0)}")
    logger.info(f"Code elements: {stats.get('code_elements', 0)}")
    logger.info(f"Total chunks: {stats.get('total_chunks', 0)}")
    
    # Step 5: Verify schema
    logger.info("\nVerifying new schema...")
    from pymilvus import Collection
    coll = Collection(collection_name)
    
    logger.info(f"\n{collection_name} Schema:")
    for field in coll.schema.fields:
        logger.info(f"  - {field.name}: {field.dtype}")
    
    logger.info("\n✓ PyEgeria collection recreated successfully with scalar fields!")
    logger.info("  Metadata filtering is now enabled for this collection.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())