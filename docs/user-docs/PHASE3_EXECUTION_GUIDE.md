# Phase 3: Re-Ingestion & Validation Execution Guide

**Status**: Ready to Execute  
**Prerequisites**: Phase 1 (Monitoring) and Phase 2 (Parameters) complete  
**Goal**: Reduce hallucination rate from 80% to 27% (66% reduction)

## Overview

Phase 3 executes the improvements designed in Phases 1-2:
1. Ingest new specialized collections with optimized parameters
2. Validate routing and retrieval quality
3. Measure hallucination rate reduction
4. Compare baseline metrics

## Prerequisites

### 1. Verify Phase 2 Implementation
```bash
# Check that collection parameters are defined
python -c "from advisor.collection_config import get_collection; \
  c = get_collection('egeria_concepts'); \
  print(f'chunk_size={c.chunk_size}, min_score={c.min_score}')"
```

Expected output: `chunk_size=768, min_score=0.45`

### 2. Clone egeria-docs Repository
```bash
cd ~/localGit/egeria-v6
git clone https://github.com/odpi/egeria-docs.git
cd egeria-docs
git pull  # Ensure latest version
```

### 3. Verify Milvus is Running
```bash
# Check Milvus status
docker ps | grep milvus

# If not running, start it
docker-compose up -d
```

### 4. Activate Virtual Environment
```bash
cd ~/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate
```

## Step 1: Capture Baseline (Before Optimization)

Capture current metrics before making changes:

```bash
# Run validation with current system
python scripts/validate_phase3_improvements.py \
  --output baseline_before.json

# This will:
# - Test 25 queries across 5 query types
# - Measure hallucination rate
# - Calculate citation and honesty rates
# - Save results to baseline_before.json
```

**Expected Results** (current system):
- Overall hallucination rate: ~80%
- CONCEPT queries: ~85% hallucination
- TYPE queries: ~80% hallucination
- CODE queries: ~60% hallucination

## Step 2: Ingest Specialized Collections

Ingest the three new specialized collections with optimized parameters:

### Option A: Ingest All Collections at Once
```bash
python scripts/ingest_specialized_collections.py \
  --all \
  --repo-path ~/localGit/egeria-v6/egeria-docs \
  --drop-existing
```

### Option B: Ingest Collections Individually
```bash
# Ingest concepts collection (high precision)
python scripts/ingest_specialized_collections.py \
  --collection egeria_concepts \
  --repo-path ~/localGit/egeria-v6/egeria-docs \
  --drop-existing

# Ingest types collection (complete definitions)
python scripts/ingest_specialized_collections.py \
  --collection egeria_types \
  --repo-path ~/localGit/egeria-v6/egeria-docs \
  --drop-existing

# Ingest general collection (tutorials)
python scripts/ingest_specialized_collections.py \
  --collection egeria_general \
  --repo-path ~/localGit/egeria-v6/egeria-docs \
  --drop-existing
```

**Expected Output**:
```
Collection egeria_concepts ingestion complete!
Total files: ~150
Total chunks: ~800

Collection egeria_types ingestion complete!
Total files: ~200
Total chunks: ~600

Collection egeria_general ingestion complete!
Total files: ~500
Total chunks: ~1200
```

## Step 3: Enable New Collections

Update collection configuration to enable new collections:

```python
# Edit advisor/collection_config.py
# Change these lines:

EGERIA_CONCEPTS_COLLECTION.enabled = True   # Was: False
EGERIA_TYPES_COLLECTION.enabled = True      # Was: False
EGERIA_GENERAL_COLLECTION.enabled = True    # Was: False
EGERIA_DOCS_COLLECTION.enabled = False      # Was: True (disable old collection)
```

Or use Python to enable them:

```bash
python -c "
from advisor.collection_config import *
enable_collection('egeria_concepts')
enable_collection('egeria_types')
enable_collection('egeria_general')
disable_collection('egeria_docs')
print('Collections updated!')
"
```

## Step 4: Verify Routing

Test that queries route to the correct specialized collections:

```bash
# Test concept query routing
python scripts/test_collection_routing.py \
  --query "What is metadata governance?"

# Expected: Routes to egeria_concepts (priority 12)

# Test type query routing
python scripts/test_collection_routing.py \
  --query "What is the Asset entity type?"

# Expected: Routes to egeria_types (priority 11)

# Test tutorial query routing
python scripts/test_collection_routing.py \
  --query "How do I get started with Egeria?"

# Expected: Routes to egeria_general (priority 9)
```

## Step 5: Capture Baseline (After Optimization)

Run validation again with optimized system:

```bash
python scripts/validate_phase3_improvements.py \
  --output baseline_after.json \
  --baseline baseline_before.json

# This will:
# - Test same 25 queries
# - Measure new hallucination rate
# - Compare with baseline_before.json
# - Show improvement percentages
```

**Expected Results** (optimized system):
- Overall hallucination rate: ≤27% (66% reduction)
- CONCEPT queries: ≤20% hallucination (76% reduction)
- TYPE queries: ≤25% hallucination (69% reduction)
- CODE queries: ≤25% hallucination (58% reduction)

## Step 6: Compare Baselines

Generate detailed comparison report:

```bash
python scripts/validate_phase3_improvements.py \
  --compare baseline_before.json baseline_after.json

# This will show:
# - Overall improvement
# - Per-query-type improvements
# - Whether target (27%) was achieved
```

## Step 7: Monitor with MLflow

View detailed metrics in MLflow:

```bash
# Start MLflow UI
mlflow ui --port 5000

# Open browser to http://localhost:5000
# Navigate to experiment: "egeria_advisor"
# Compare runs before/after optimization
```

**Key Metrics to Check**:
- `retrieval.avg_score` - Should increase
- `retrieval.result_count` - Should be appropriate per collection
- `collection.hit_rate` - Should improve for specialized collections
- `assembly.diversity` - Should increase (better variety)

## Step 8: Validate Collection Metrics

Check per-collection performance:

```bash
python scripts/collect_collection_health.py

# This will show:
# - Hit rate per collection
# - Average scores
# - Result counts
# - Collection utilization
```

**Expected Improvements**:
- `egeria_concepts`: High hit rate, high avg_score (0.45+)
- `egeria_types`: Moderate hit rate, high avg_score (0.42+)
- `egeria_general`: Good hit rate, moderate avg_score (0.38+)

## Troubleshooting

### Issue: Collections Not Found

**Symptom**: "Collection not found" errors

**Solution**:
```bash
# List all collections in Milvus
python -c "from advisor.vector_store import get_vector_store; \
  vs = get_vector_store(); \
  print(vs.list_collections())"

# Re-ingest if missing
python scripts/ingest_specialized_collections.py --all
```

### Issue: High Hallucination Rate Persists

**Symptom**: Hallucination rate still >40% after optimization

**Possible Causes**:
1. Old egeria_docs collection still enabled
2. Collections not properly ingested
3. Routing not working correctly

**Solution**:
```bash
# 1. Verify old collection is disabled
python -c "from advisor.collection_config import get_collection; \
  c = get_collection('egeria_docs'); \
  print(f'enabled={c.enabled}')"  # Should be False

# 2. Check collection sizes
python -c "from advisor.vector_store import get_vector_store; \
  vs = get_vector_store(); \
  for name in ['egeria_concepts', 'egeria_types', 'egeria_general']: \
    count = vs.get_collection_stats(name)['entity_count']; \
    print(f'{name}: {count} entities')"

# 3. Test routing manually
python scripts/test_collection_routing.py --query "What is an asset?"
```

### Issue: Low Citation Rate

**Symptom**: Citation rate <50%

**Solution**:
- Check that prompt templates include anti-hallucination instructions
- Verify retrieval is returning relevant results
- Increase min_score threshold if needed

## Success Criteria

Phase 3 is successful when:

- ✅ All three specialized collections ingested
- ✅ Collections properly indexed in Milvus
- ✅ Routing directs queries to correct collections
- ✅ Overall hallucination rate ≤27%
- ✅ CONCEPT queries ≤20% hallucination
- ✅ TYPE queries ≤25% hallucination
- ✅ CODE queries ≤25% hallucination
- ✅ Citation rate ≥70%
- ✅ Metrics logged in MLflow

## Next Steps After Phase 3

Once Phase 3 is validated:

1. **Monitor Production Usage**
   - Track hallucination rate over time
   - Collect user feedback
   - Identify edge cases

2. **Iterate on Parameters**
   - Fine-tune min_score thresholds
   - Adjust chunk sizes if needed
   - Optimize top_k values

3. **Expand Collections**
   - Add more specialized collections
   - Ingest additional repositories
   - Improve domain term coverage

4. **Enhance Monitoring**
   - Add real-time dashboards
   - Set up alerting for quality degradation
   - Track user satisfaction metrics

## Files Created in Phase 3

- `scripts/ingest_specialized_collections.py` - Collection ingestion script
- `scripts/validate_phase3_improvements.py` - Validation and comparison script
- `docs/user-docs/PHASE3_EXECUTION_GUIDE.md` - This guide

## References

- **Phase 1**: `docs/design/MONITORING_IMPLEMENTATION_STATUS.md`
- **Phase 2**: `docs/design/PHASE2_COLLECTION_PARAMETERS_IMPLEMENTATION.md`
- **Collection Split**: `docs/design/EGERIA_DOCS_SPLIT_STRATEGY.md`
- **Query Classification**: `docs/design/QUERY_CLASSIFICATION_AND_TRACKING.md`

## Support

If you encounter issues:

1. Check logs in `.venv/logs/`
2. Review MLflow experiments
3. Verify Milvus is running
4. Check collection configurations
5. Test routing manually

For questions, refer to:
- `TROUBLESHOOTING.md`
- `docs/design/MONITORING_NEXT_STEPS.md`
- MLflow experiment tracking