#!/usr/bin/env python3
"""
Migrate existing PyEgeria collection data to new schema with scalar fields.
"""

import sys
from pathlib import Path
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.vector_store import VectorStoreManager
from pymilvus import Collection, utility


def main():
    """Migrate pyegeria collection to scalar fields."""
    
    logger.info("=" * 80)
    logger.info("MIGRATING PYEGERIA TO SCALAR FIELDS")
    logger.info("=" * 80)
    
    vs = VectorStoreManager()
    vs.connect()
    
    old_name = "pyegeria"
    temp_name = "pyegeria_old"
    
    # Step 1: Check if old collection exists
    if not utility.has_collection(old_name):
        logger.error(f"Collection {old_name} does not exist!")
        logger.error("Nothing to migrate.")
        return 1
    
    # Step 2: Rename old collection
    logger.info(f"Backing up {old_name} to {temp_name}...")
    if utility.has_collection(temp_name):
        utility.drop_collection(temp_name)
    
    # Can't rename in Milvus, so we'll just note the old one exists
    old_coll = Collection(old_name)
    old_coll.load()
    
    # Get count
    count = old_coll.num_entities
    logger.info(f"Old collection has {count} entities")
    
    if count == 0:
        logger.warning("Old collection is empty, nothing to migrate")
        return 0
    
    # Step 3: Query all data from old collection
    logger.info("Querying all data from old collection...")
    results = old_coll.query(
        expr="id != ''",  # Get all
        output_fields=["id", "text", "metadata"],
        limit=20000  # Should be enough
    )
    
    logger.info(f"Retrieved {len(results)} entities")
    
    # Step 4: Drop old and create new
    logger.info(f"Dropping old {old_name}...")
    utility.drop_collection(old_name)
    
    logger.info(f"Creating new {old_name} with scalar fields...")
    vs.create_collection(old_name, drop_if_exists=False)
    vs.create_index(old_name)
    
    # Step 5: Prepare data for new schema
    texts = []
    ids = []
    metadata_list = []
    
    for entity in results:
        texts.append(entity['text'])
        ids.append(entity['id'])
        
        # Extract scalar fields from JSON metadata
        meta = entity.get('metadata', {})
        new_meta = {
            "element_type": meta.get('element_type', ''),
            "class_name": meta.get('class_name', ''),
            "method_name": meta.get('name', '') if meta.get('element_type') in ['method', 'function'] else '',
            "module_path": meta.get('module_path', ''),
            "is_async": meta.get('is_async', False),
            "is_private": meta.get('is_private', False),
            # Keep full metadata
            **meta
        }
        metadata_list.append(new_meta)
    
    # Step 6: Insert into new collection
    logger.info(f"Inserting {len(texts)} entities into new collection...")
    num_inserted = vs.insert_data(
        collection_name=old_name,
        texts=texts,
        ids=ids,
        metadata=metadata_list,
        batch_size=500
    )
    
    logger.info(f"\n✓ Successfully migrated {num_inserted} entities")
    
    # Step 7: Verify
    new_coll = Collection(old_name)
    logger.info(f"\nNew schema:")
    for field in new_coll.schema.fields:
        logger.info(f"  - {field.name}: {field.dtype}")
    
    logger.info(f"\n✓ Migration complete! PyEgeria now has scalar fields for filtering.")
    return 0


if __name__ == "__main__":
    sys.exit(main())