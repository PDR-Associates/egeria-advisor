# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Egeria Advisor is a RAG (Retrieval-Augmented Generation) system providing intelligent assistance for [Egeria](https://egeria-project.org/) and pyegeria users. It uses local LLMs (Ollama), sentence-transformer embeddings, and a pgvector (PostgreSQL) vector store across 9 specialized collections (~88,900 entities total).

## Setup

```bash
# Activate virtual environment
source activate_venv.sh

# Install with dev dependencies
pip install -e ".[dev]"
```

Requires Python 3.12+. External services must be running locally:
- **pgvector** at `localhost:5442` (PostgreSQL with pgvector extension — database: `egeria_advisor`, user: `egeria_advisor`)
- **Ollama** at `localhost:11434` (LLM inference — llama3.1:8b, codellama:13b)
- **MLflow** at `localhost:5025` (optional, for experiment tracking)

## Commands

```bash
# Query (one-shot)
egeria-advisor "What is a glossary term in Egeria?"

# Interactive multi-turn session
egeria-advisor --interactive

# Agent mode (conversational with memory via BeeAI)
egeria-advisor --agent

# Disable MLflow tracking
egeria-advisor --no-track "Show me asset management examples"

# Terminal dashboard (5-second refresh)
python -m advisor.dashboard.terminal_dashboard

# Incremental indexing for a collection
python -m advisor.incremental_indexer --collection pyegeria

# Count vectors per collection
python scripts/count_vectors.py
```

## Testing

```bash
# Quick E2E test suite
python scripts/test_end_to_end.py --quick

# Full test suite
python scripts/test_end_to_end.py --full

# Specific categories
python scripts/test_end_to_end.py --categories environment,config,vector_store

# Pytest with coverage
pytest tests/ -v
pytest --cov=advisor --cov-report=html

# Specialized test scripts
python scripts/test_incremental_indexing.py
python scripts/test_vector_search.py
```

## Architecture

### Query Flow

```
User Query
  → CLI (advisor/cli/main.py)
  → RAGSystem (advisor/rag_system.py)          ← main orchestrator
      ├─ QueryCache (advisor/query_cache.py)    ← checked first; large speedup on hits
      ├─ QueryProcessor (advisor/query_processor.py)  ← classifies query type/intent
      │    ├─ quantitative  → Analytics (direct answer from SQLite metrics)
      │    ├─ relationship  → RelationshipQueryHandler
      │    ├─ report        → ReportPipeline (advisor/report_pipeline.py)
      │    ├─ command       → DrEgeriaActionAgent (advisor/agents/dr_egeria_agent.py)
      │    └─ general/code  → RAG retrieval + LLM generation (below)
      ├─ CollectionRouter (advisor/collection_router.py)  ← selects relevant collections
      ├─ RAGRetrieval (advisor/rag_retrieval.py)
      │    └─ MultiCollectionStore (advisor/multi_collection_store.py)
      │         └─ pgvector (HNSW index, 384-dim sentence-transformer embeddings)
      ├─ LLMClient (advisor/llm_client.py)      ← Ollama wrapper
      └─ PromptTemplates (advisor/prompt_templates.py)
```

MLflow tracking runs in a background daemon thread after `query()` returns — it does not block the CLI response.

### Vector Collections (9 active)

| Collection | Content |
|---|---|
| `pyegeria` | Python SDK code & tests |
| `pyegeria_cli` | hey_egeria CLI commands |
| `pyegeria_drE` | Dr. Egeria markdown translator code |
| `egeria_java` | Core Java library (OMAS, OMAG, OMRS) |
| `egeria_concepts` | Core concept definitions |
| `egeria_types` | Type system and schema definitions |
| `egeria_general` | Tutorials, guides, and how-tos |
| `egeria_workspaces` | Jupyter notebooks and deployment examples |
| `egeria_templates` | Dr. Egeria markdown command templates |

`egeria_docs` is disabled — split into `egeria_concepts`, `egeria_types`, and `egeria_general`.

The pgvector table for `pyegeria_drE` is named `pyegeria_dre` (normalized to lowercase). The `_TABLE_NAME_MAP` in `advisor/vector_store_pg.py` handles this mapping.

The `CollectionRouter` selects 1–N collections per query based on classified intent. RAG parameters: chunk_size=512, top_k=10, min_score=0.30.

### Vector Store Backends

`BaseVectorStore` (`advisor/vector_store_base.py`) is the abstract base class for all backends.

- **`PgVectorStore`** (`advisor/vector_store_pg.py`) — active backend; uses `ThreadedConnectionPool`
- **`MilvusVectorStore`** (`advisor/vector_store.py`) — legacy; kept for reference

`get_vector_store()` in `advisor/vector_store.py` reads `vector_store_backend` from `config/advisor.yaml` and returns the correct instance. Currently set to `pgvector`.

### Agent Modes (`advisor/agents/`)

| Agent | Handles |
|---|---|
| `DrEgeriaActionAgent` | `command` queries — finds Dr. Egeria templates and composes/executes pyegeria commands |
| `PyEgeriaAgent` | Python SDK code questions with exhaustive method lookup |
| `ConversationAgent` | Multi-turn sessions (BeeAI framework) |
| `CLICommandAgent` | hey_egeria CLI command lookup and generation |

### Data Pipeline (`advisor/data_prep/`)

`pipeline.py` ingests source repositories (egeria Python, egeria Java, docs, notebooks) using `CodeParser`, `DocParser`, `CLIIndexer`, and `MetadataExtractor`. Run `scripts/clone_repos.py` to fetch source repos before indexing. Use `scripts/ingest_collections.py` to re-index a collection into pgvector.

### Observability

- **SQLite** (`metrics_collector.py`) — query latency, collection health, system resources; always active
- **MLflow** (`mlflow_tracking.py`) — experiment tracking; non-blocking background thread
- **FeedbackCollector** — user thumbs up/down tracking from interactive mode
- **Analytics** (`analytics.py`) — aggregated reporting for quantitative queries

## Configuration

Primary config: `config/advisor.yaml`. Environment overrides: `.env` (copy from `.env.example`).

Key config sections: `pgvector`, `vector_store_backend`, `llm`, `embeddings`, `rag`, `observability`, `agents`.

Settings are managed via Pydantic models in `advisor/config.py`.

## Code Style

Black + Ruff for formatting/linting, MyPy for type checking. Configured in `pyproject.toml`.

```bash
black advisor/
ruff check advisor/
mypy advisor/
```
