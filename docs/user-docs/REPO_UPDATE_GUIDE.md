# Repository Update and Incremental Indexing Guide

This guide explains how to update cloned repositories and incrementally update the Milvus vector store with new or modified content.

## Overview

The Egeria Advisor system clones source repositories and indexes their content into Milvus collections. When repositories are updated, you can use incremental indexing to efficiently update only the changed content without re-indexing everything.

## Quick Reference

```bash
# 1. Update repositories from GitHub
./scripts/update_repos.sh

# 2. Check what would be ingested (dry run)
python scripts/ingest_collections.py --dry-run --phase all

# 3. Ingest specific collection
python scripts/ingest_collections.py --collection pyegeria --force

# 4. Ingest all collections
python scripts/ingest_collections.py --phase all --force
```

## Step-by-Step Guide

### 1. Initial Repository Setup

If you haven't cloned the repositories yet:

```bash
# Clone all required repositories
python scripts/clone_repos.py

# This creates:
# data/repos/egeria-python/
# data/repos/egeria/
# data/repos/egeria-docs/
# data/repos/egeria-workspaces/
```

### 2. Update Repositories from GitHub

#### Option A: Manual Update (Recommended)

Update each repository individually:

```bash
# Update egeria-python (pyegeria, pyegeria_cli, pyegeria_drE)
cd data/repos/egeria-python
git pull origin main
cd ../../..

# Update egeria (Java code)
cd data/repos/egeria
git pull origin main
cd ../../..

# Update egeria-docs (documentation)
cd data/repos/egeria-docs
git pull origin main
cd ../../..

# Update egeria-workspaces (examples)
cd data/repos/egeria-workspaces
git pull origin main
cd ../../..
```

#### Option B: Automated Update Script

Create a helper script `scripts/update_repos.sh`:

```bash
#!/bin/bash
# Update all Egeria repositories

set -e

REPOS_DIR="data/repos"

echo "Updating Egeria repositories..."

for repo in egeria-python egeria egeria-docs egeria-workspaces; do
    if [ -d "$REPOS_DIR/$repo" ]; then
        echo ""
        echo "Updating $repo..."
        cd "$REPOS_DIR/$repo"
        git pull origin main
        cd ../../..
        echo "✓ $repo updated"
    else
        echo "⚠ $repo not found, skipping"
    fi
done

echo ""
echo "✓ All repositories updated"
```

Make it executable and run:

```bash
chmod +x scripts/update_repos.sh
./scripts/update_repos.sh
```

### 3. Re-Ingesting Collections

After updating repositories, you need to re-ingest the collections into Milvus.

**Note:** The current implementation requires a full re-ingest (with `--force`) rather than incremental updates. Incremental indexing is planned for a future release.

#### Understanding Phases

Collections are organized into two phases for easier management:

**Phase 1 - Python Collections** (from egeria-python repo):
- `pyegeria` - Core Python client library
- `pyegeria_cli` - CLI commands (hey_egeria)
- `pyegeria_drE` - drE tools

**Phase 2 - Java, Docs, and Examples** (from multiple repos):
- `egeria_java` - Java implementation
- `egeria_docs` - Documentation
- `egeria_workspaces` - Example workspaces

You can ingest by phase or individual collection.

#### Check What Would Be Ingested (Dry Run)

See what would be ingested without actually doing it:

```bash
# Dry run for Phase 1 (Python collections)
python scripts/ingest_collections.py --dry-run --phase 1

# Dry run for all collections
python scripts/ingest_collections.py --dry-run --phase all
```

#### Ingest Specific Collection

Re-ingest a single collection:

```bash
# Ingest pyegeria collection (will skip if exists)
python scripts/ingest_collections.py --collection pyegeria

# Force re-ingest (drops and recreates collection)
python scripts/ingest_collections.py --collection pyegeria --force
```

Available collections:
- `pyegeria` - Python client library
- `pyegeria_cli` - Python CLI tools
- `pyegeria_drE` - Python drE tools
- `egeria_java` - Java implementation
- `egeria_docs` - Documentation
- `egeria_workspaces` - Example workspaces

#### Ingest by Phase

Ingest collections in phases:

```bash
# Phase 1: Python collections (pyegeria, pyegeria_cli, pyegeria_drE)
python scripts/ingest_collections.py --phase 1 --force

# Phase 2: Java, docs, workspaces
python scripts/ingest_collections.py --phase 2 --force

# All phases
python scripts/ingest_collections.py --phase all --force
```

#### Force Full Re-index

To completely rebuild collections after repository updates:

```bash
# Re-index specific collection
python scripts/ingest_collections.py --collection pyegeria --force

# Re-index all Phase 1 collections
python scripts/ingest_collections.py --phase 1 --force

# Re-index all collections
python scripts/ingest_collections.py --phase all --force
```

## How Ingestion Works

The ingestion process:

1. **Reads Configuration**: Loads collection metadata from `advisor/collection_config.py`
2. **Locates Source Files**: Finds files in `data/repos/` based on collection configuration
3. **Parses Code**: Extracts code elements (classes, functions, methods) and documentation
4. **Chunks Content**: Splits large files into manageable chunks (default: 1000 chars with 200 overlap)
5. **Generates Embeddings**: Creates vector embeddings for each chunk
6. **Stores in Milvus**: Inserts chunks with embeddings and metadata into collections
7. **Creates Index**: Builds IVF_FLAT index for efficient similarity search

**Note:** Currently, the system performs full re-ingestion. Incremental indexing (tracking file changes and updating only modified content) is planned for a future release. See `docs/design/INCREMENTAL_INDEXING_DESIGN.md` for the design.

## Monitoring Updates

### View Ingestion Statistics

The ingestion script logs detailed statistics:

```
Ingestion Summary
============================================================
pyegeria:
  Files: 156
  Chunks: 2847
egeria_docs:
  Files: 89
  Chunks: 1523
------------------------------------------------------------
Total Files: 245
Total Chunks: 4370
```

### Check Ingestion Status

View current collection status:

```bash
python scripts/check_ingestion_status.py
```

### MLflow Tracking

If MLflow is enabled, ingestion operations are tracked:

```bash
# View MLflow UI
mlflow ui --port 5000

# Navigate to: http://localhost:5000
# Look for ingestion experiments with metrics like:
# - Files processed
# - Chunks created
# - Processing time
# - Embedding generation time
```

## Automated Updates with Airflow (Future)

**Note:** Airflow integration for automated repository updates and re-ingestion is planned but not yet implemented. See `docs/design/AIRFLOW_INTEGRATION_DESIGN.md` for the design.

When implemented, Airflow will provide:

1. **Scheduled Repository Updates**: Automatically pull from GitHub on a schedule
2. **Automated Re-ingestion**: Trigger collection updates after repository changes
3. **Health Monitoring**: Regular checks of collection and system health
4. **Alerting**: Notifications when issues are detected

For now, use cron jobs or manual scripts for automation:

```bash
# Example cron job (runs daily at 2 AM)
0 2 * * * cd /path/to/egeria-advisor && ./scripts/update_repos.sh && python scripts/ingest_collections.py --phase all --force
```

## Troubleshooting

### Issue: Collection already exists error

**Solution**: Use `--force` to drop and recreate the collection:

```bash
# Force re-ingest
python scripts/ingest_collections.py --collection pyegeria --force
```

### Issue: Ingestion is slow

**Causes**:
- Large number of files
- Network latency to Milvus
- Embedding generation bottleneck

**Solutions**:
```bash
# Ingest collections one at a time
python scripts/ingest_collections.py --collection pyegeria --force

# Check Milvus connection
python scripts/check_ingestion_status.py

# Monitor resource usage
htop  # or top
```

### Issue: Git pull fails with conflicts

**Solution**: Resolve conflicts manually:

```bash
cd data/repos/egeria-python

# Check status
git status

# If conflicts, reset to remote
git fetch origin
git reset --hard origin/main

cd ../../..
```

### Issue: Collection not updating after repo update

**Solution**: You must use `--force` to re-ingest after repository updates:

```bash
# Verify repository was updated
cd data/repos/egeria-python && git log -1

# Force re-ingest the collection
cd ../../..
python scripts/ingest_collections.py --collection pyegeria --force
```

**Note:** The system currently requires full re-ingestion. Automatic change detection and incremental updates are not yet implemented.

## Best Practices

### 1. Regular Updates

Update repositories regularly to keep content fresh:

```bash
# Weekly update schedule (cron job)
0 2 * * 0 cd /path/to/egeria-advisor && ./scripts/update_repos.sh && python scripts/ingest_collections.py --phase all --force
```

### 2. Monitor Ingestion Performance

Track ingestion metrics:
- Time per collection
- Number of files processed
- Number of chunks created
- Embedding generation time
- Milvus insertion time

Use MLflow to track these metrics over time.

### 3. Backup Before Major Updates

Before major repository updates or re-ingestion:

```bash
# Backup Milvus data (procedures depend on your deployment)
# For Docker: docker exec milvus-standalone /bin/bash -c "..."

# Note: File tracker database is only used if incremental indexing is implemented
```

### 4. Test in Development First

Test ingestion in a development environment before production:

```bash
# Dry run to see what would be ingested
python scripts/ingest_collections.py --dry-run --phase all

# Review file counts and patterns
```

### 5. Use Scheduled Jobs for Automation

For production systems, use cron jobs or systemd timers:

```bash
# Example cron job (weekly updates)
0 2 * * 0 cd /path/to/egeria-advisor && ./scripts/update_repos.sh && python scripts/ingest_collections.py --phase all --force >> /var/log/egeria-advisor/updates.log 2>&1
```

## Advanced Usage

### Custom Update Frequency

Modify Airflow DAG schedule:

```python
# In airflow/dags/incremental_update_dag.py
dag = DAG(
    'egeria_incremental_update',
    schedule_interval='0 */3 * * *',  # Every 3 hours
    ...
)
```

### Selective File Updates

Update only specific file patterns:

```python
from advisor.incremental_indexer import IncrementalIndexer

indexer = IncrementalIndexer(collection_name="pyegeria")

# Only update Python files in specific directory
changes = indexer.detect_changes(
    source_paths=[Path("data/repos/egeria-python/pyegeria")],
    file_patterns=["*.py"]
)

result = indexer.apply_updates(changes)
```

### Integration with CI/CD

Trigger updates from GitHub Actions:

```yaml
# .github/workflows/update-index.yml
name: Update RAG Index
on:
  push:
    branches: [main]
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Trigger incremental update
        run: |
          curl -X POST http://your-airflow-server/api/v1/dags/egeria_incremental_update/dagRuns
```

## Related Documentation

- [Incremental Indexing Design](../design/INCREMENTAL_INDEXING_DESIGN.md)
- [Multi-Collection Usage Guide](MULTI_COLLECTION_USAGE_GUIDE.md)
- [Airflow Integration Design](../design/AIRFLOW_INTEGRATION_DESIGN.md)
- [Quick Start Guide](QUICK_START.md)

## Support

For issues or questions:
1. Check [TROUBLESHOOTING.md](../../TROUBLESHOOTING.md)
2. Review logs in `logs/` directory
3. Check MLflow experiments for update metrics
4. Open an issue on GitHub