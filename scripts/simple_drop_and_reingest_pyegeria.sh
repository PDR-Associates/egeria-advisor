#!/bin/bash
# Simple script to drop and re-ingest PyEgeria collection with scalar fields

echo "========================================="
echo "DROP AND RE-INGEST PYEGERIA COLLECTION"
echo "========================================="
echo ""

# Drop the old collection
echo "Step 1: Dropping old pyegeria collection..."
python -c "
from advisor.vector_store import get_vector_store
vs = get_vector_store()
vs.connect()
try:
    vs.drop_collection('pyegeria')
    print('✓ Dropped pyegeria collection')
except Exception as e:
    print(f'Note: {e}')

try:
    vs.drop_collection('pyegeria_drE')
    print('✓ Dropped pyegeria_drE collection')
except Exception as e:
    print(f'Note: {e}')
"

echo ""
echo "Step 2: Re-ingesting PyEgeria with scalar fields..."
python scripts/simple_reingest_pyegeria.py

echo ""
echo "========================================="
echo "DONE!"
echo "========================================="
echo ""
echo "Test with: egeria-advisor -a"
echo "Then ask: What is ProjectManager?"