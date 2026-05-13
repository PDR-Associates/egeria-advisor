# Collection Maintenance Guide

Complete guide for maintaining Egeria Advisor collections, statistics, and analytics.

## Table of Contents

1. [Collection Overview](#collection-overview)
2. [PyEgeria Collection](#pyegeria-collection)
3. [Specialized Collections](#specialized-collections)
4. [Statistics and Analytics](#statistics-and-analytics)
5. [Troubleshooting](#troubleshooting)

---

## Collection Overview

### Available Collections

| Collection | Description | Source |
|------------|-------------|--------|
| **pyegeria** | PyEgeria code (classes, methods, modules) | `data/repos/egeria-python` |
| **egeria_docs** | Egeria documentation | `data/repos/egeria-docs` |
| **cli_commands** | CLI command documentation | Parsed from CLI help |
| **code_examples** | Code examples and notebooks | `data/repos/egeria-python/examples` |

### Check Collection Status

```bash
# List all collections
python scripts/check_collection_names.py

# Check collection health
python scripts/collect_collection_health.py

# Check specific collection contents
python scripts/check_projectmanager.py  # Example for PyEgeria
```

---

## PyEgeria Collection

### Initial Setup

```bash
# 1. Clone/update repositories
python scripts/clone_repos.py

# 2. Ingest all collections (includes PyEgeria)
python scripts/ingest_collections.py
```

### Update PyEgeria Collection

When PyEgeria code changes:

```bash
# Option 1: Full re-ingest (recommended)
python scripts/ingest_collections.py

# Option 2: Simple re-ingest (if collection exists)
python scripts/simple_reingest_pyegeria.py

# Option 3: Drop and re-create (if schema changed)
./scripts/simple_drop_and_reingest_pyegeria.sh
```

### Verify PyEgeria Collection

```bash
# Check if collection has data
python scripts/check_projectmanager.py

# Test PyEgeria detection
python scripts/test_pyegeria_detection.py

# Test full agent flow
python scripts/test_full_agent_flow.py
```

### PyEgeria Collection Schema

The collection includes these scalar fields for efficient filtering:

- `class_name` - Class name (e.g., "ProjectManager")
- `method_name` - Method name (e.g., "create_project")
- `element_type` - Type: "class", "method", "module", "function"
- `module_path` - Python module path
- `is_async` - Boolean: async method
- `is_private` - Boolean: private method

---

## Specialized Collections

### What Are Specialized Collections?

Specialized collections contain:
- **CLI Commands** - Parsed from `egeria-advisor --help` and subcommands
- **Code Examples** - Jupyter notebooks, Python examples
- **Documentation** - Markdown files, guides

### Update Specialized Collections

```bash
# Re-ingest specialized collections
python scripts/ingest_specialized_collections.py
```

This will:
1. Parse CLI commands from the installed `egeria-advisor` command
2. Extract code examples from repositories
3. Process documentation files
4. Update the respective collections

### Enable/Disable Collections

Edit `config/advisor.yaml`:

```yaml
collections:
  pyegeria:
    enabled: true
    priority: 1
  
  cli_commands:
    enabled: true  # Set to false to disable
    priority: 2
  
  code_examples:
    enabled: true
    priority: 3
```

---

## Statistics and Analytics

### Update Collection Statistics

```bash
# Collect health metrics for all collections
python scripts/collect_collection_health.py
```

This updates:
- Entity counts
- Index status
- Schema information
- Collection health scores

### View Analytics Dashboard

```bash
# Terminal dashboard (text-based)
python -m advisor.dashboard.terminal_dashboard

# Streamlit dashboard (web-based)
python -m advisor.dashboard.streamlit_dashboard
```

### Generate Enhanced Analytics

```bash
# Test enhanced analytics
python scripts/test_enhanced_analytics.py

# Generate enhanced relationships
python scripts/generate_enhanced_relationships.py
```

### MLflow Tracking

View experiment tracking:

```bash
# Start MLflow UI
mlflow ui --port 5025

# Then open: http://localhost:5025
```

Experiments tracked:
- Query processing
- RAG retrieval
- Agent interactions
- Model performance

### Monitoring Integration

```bash
# Test monitoring integration
python scripts/test_monitoring_integration.py

# Test enhanced MLflow tracking
python scripts/test_enhanced_mlflow.py
```

---

## Troubleshooting

### Collection Has No Data

**Symptom:** Queries return "I couldn't find specific information"

**Solution:**
```bash
# Check collection
python scripts/check_collection_names.py

# Re-ingest
python scripts/ingest_collections.py
```

### Collection Missing Scalar Fields

**Symptom:** Error: `field class_name not exist`

**Solution:**
```bash
# Drop and re-create with correct schema
./scripts/simple_drop_and_reingest_pyegeria.sh
```

### PyEgeria Detection Not Working

**Symptom:** PyEgeria queries route to wrong agent

**Solution:**
```bash
# Test detection
python scripts/test_pyegeria_detection.py

# Check routing config
cat config/routing.yaml

# Update detection patterns in routing.yaml if needed
```

### Cache Issues

**Symptom:** Old data persists after updates

**Solution:**
```bash
# Clear query cache
egeria-advisor -a
agent> /clear-query-cache

# Or clear all caches
rm -rf cache/*.json
```

### Performance Issues

**Symptom:** Slow queries or high memory usage

**Solution:**
```bash
# Check collection health
python scripts/collect_collection_health.py

# Test cache performance
python scripts/test_cache_performance.py

# Optimize embeddings (if using ONNX)
python scripts/convert_to_onnx.py
```

---

## Maintenance Schedule

### Daily
- Monitor MLflow experiments
- Check error logs

### Weekly
- Update repositories: `python scripts/clone_repos.py`
- Re-ingest if code changed: `python scripts/ingest_collections.py`
- Collect health metrics: `python scripts/collect_collection_health.py`

### Monthly
- Review analytics dashboard
- Update routing configuration if needed
- Clean up old experiment data

### As Needed
- Update specialized collections when CLI changes
- Re-create collections if schema changes
- Update documentation when features change

---

## Quick Reference

### Common Commands

```bash
# Start agent
egeria-advisor -a

# Update everything
python scripts/clone_repos.py && python scripts/ingest_collections.py

# Check status
python scripts/check_collection_names.py
python scripts/collect_collection_health.py

# View analytics
python -m advisor.dashboard.terminal_dashboard

# Clear caches
egeria-advisor -a
agent> /clear-query-cache
```

### Configuration Files

- `config/advisor.yaml` - Main configuration
- `config/routing.yaml` - Query routing patterns
- `config/mcp_servers.json` - MCP server configuration

### Log Files

- MLflow experiments: `mlruns/`
- Collection health: Stored in Milvus metadata
- Application logs: Console output (use `--debug` flag)

---

## See Also

- [Query Routing Guide](QUERY_ROUTING_GUIDE.md)
- [Data-Driven Routing Guide](DATA_DRIVEN_ROUTING_GUIDE.md)
- [MLflow Tracking Guide](MLFLOW_ENHANCED_TRACKING.md)
- [Testing Guide](TESTING_GUIDE.md)