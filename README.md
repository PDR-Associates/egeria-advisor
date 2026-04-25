# Egeria Advisor

Experimental AI-powered advisor for the Egeria Python library using local LLMs and RAG.
The goal is to provide a useful advisor for Egeria and pyegeria users. You should be able to ask questions about the
concepts and code, ask for examples, find definitions, and ask the advisor to take actions on your behalf using Dr. Egeria
markdown commands or pyegeria directly.

This is also a testbed for experiments with AI, RAG, Agents, LLMs, and more. There are experimental features and ideas
that are not yet fully cooked, integrated, or tested.

This is a work in progress. There are known limitations and bugs, and the system is not production-ready.

The accuracy of the results is still only fair at best. Hallucinations and errors do occur, and results are tracked and
feedback collected to drive ongoing improvements.

Feedback and comments are welcome. Please share your thoughts and suggestions to help improve the system.

## Overview

Egeria Advisor is a RAG (Retrieval-Augmented Generation) system that helps users and maintainers work with the Egeria
Python library by providing:

### Core Capabilities

- **Multi-Collection Search**: 9 specialized repository collections (~88,900 entities) with intelligent routing
- **Action Execution**: Dr. Egeria integration to compose and execute pyegeria commands from natural-language requests
- **Report Generation**: MCP-based report pipeline for structured Egeria data queries
- **Conversational Agent**: Multi-turn conversations with context and memory (BeeAI)
- **Code Analysis**: Deep understanding of Python/Java code, APIs, and patterns
- **Performance Optimization**: Query cache speedup, parallel collection search, universal GPU support
- **Enhanced Tracking**: MLflow integration for metrics, resource monitoring, and accuracy
- **Incremental Updates**: 10-100x faster updates with file change tracking
- **Real-time Monitoring**: Terminal dashboard with metrics collection

### Key Features

✅ **Multi-Collection Architecture**: 9 specialized collections with intelligent query routing  
✅ **Action & Report Pipeline**: Dr. Egeria command execution and MCP-based report generation  
✅ **Universal GPU Support**: Auto-detection for CUDA, ROCm, MPS, and CPU  
✅ **Conversational Agent**: BeeAI framework integration with memory  
✅ **Rich CLI**: 3 interaction modes (query, interactive, agent)  
✅ **MLflow Tracking**: Experiment and query tracking (background, non-blocking)  
✅ **Incremental Indexing**: Fast updates with SQLite-based change detection  
✅ **Monitoring Dashboard**: Real-time metrics and health monitoring  

## Architecture

### Technology Stack

- **LLM**: Ollama (local) @ localhost:11434
  - Primary Model: llama3.1:8b (fast, general purpose)
  - Code Model: codellama:13b (code-specialized)
- **Vector Store**: pgvector (PostgreSQL) @ localhost:5442
  - 9 specialized collections (~88,900 entities)
  - 384-dimensional HNSW embeddings
  - Database: `egeria_advisor`, user: `egeria_advisor`
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2 (local)
  - Universal device support (CUDA/ROCm/MPS/CPU)
- **Experiment Tracking**: MLflow @ localhost:5025 (optional)
- **Metrics Storage**: SQLite (query metrics, collection health, system resources)
- **Agent Framework**: BeeAI for conversational interactions

### Collections

| Collection | Purpose |
|-----------|---------|
| `pyegeria` | Core Python library code and tests |
| `pyegeria_cli` | hey_egeria CLI commands and tools |
| `pyegeria_drE` | Dr. Egeria markdown-to-pyegeria translator |
| `egeria_java` | Core Java library (OMAS, OMAG, OMRS) |
| `egeria_concepts` | Core concept definitions |
| `egeria_types` | Type system and schema definitions |
| `egeria_general` | Tutorials, guides, and how-tos |
| `egeria_workspaces` | Jupyter notebooks, deployment configs, examples |
| `egeria_templates` | Dr. Egeria markdown command templates |

Collections are defined in `advisor/collection_config.py`. Query routing selects 1–N collections per query based on
classified intent; see `advisor/collection_router.py`.

### Query Flow

```
User Query
  → CLI (advisor/cli/main.py)
  → RAGSystem (advisor/rag_system.py)
      ├─ QueryCache                   ← checked first; large speedup on cache hits
      ├─ QueryProcessor               ← classifies query type/intent
      │    ├─ quantitative  → Analytics module (direct SQL answer)
      │    ├─ relationship  → Relationship graph handler
      │    ├─ report        → MCP report pipeline (advisor/report_pipeline.py)
      │    ├─ command       → DrEgeriaActionAgent (advisor/agents/dr_egeria_agent.py)
      │    └─ general       → RAG retrieval + LLM generation (below)
      ├─ CollectionRouter             ← selects relevant collections
      ├─ RAGRetrieval
      │    └─ MultiCollectionStore   ← parallel search across collections
      │         └─ pgvector (HNSW, 384-dim sentence-transformer embeddings)
      ├─ LLMClient                   ← Ollama wrapper
      └─ PromptTemplates
```

## Quick Start

### Prerequisites

Ensure these services are running:

```bash
# PostgreSQL with pgvector (vector store)
psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c "SELECT COUNT(*) FROM pyegeria;"

# Ollama (LLM inference)
curl http://localhost:11434/api/tags

# MLflow (optional — for experiment tracking)
curl http://localhost:5025

# Egeria server (if running action/report queries)
curl -k https://localhost:9443/open-metadata/platform-services/users/garygeeke/server-platform/origin
```

### Installation

```bash
# Navigate to project
cd /Users/dwolfson/localGit/egeria-v6/egeria-advisor

# Activate virtual environment
source activate_venv.sh

# Install with dev dependencies
pip install -e ".[dev]"

# Verify setup
python -c "from advisor.config import settings; print('✓ Config loaded')"
```

### Pull Ollama Models

```bash
# If using Docker
docker exec ollama ollama pull llama3.1:8b
docker exec ollama ollama pull codellama:13b

# If using native Ollama
ollama pull llama3.1:8b
ollama pull codellama:13b
```

## Usage

### 1. Query Mode (Direct Questions)

```bash
# Simple question
egeria-advisor "What is a glossary term in Egeria?"

# Ask for code examples
egeria-advisor "How do I create a glossary in pyegeria?"

# With MLflow tracking enabled (default)
egeria-advisor "Show me asset management examples"

# Without MLflow tracking
egeria-advisor --no-track "What is a metadata repository?"

# JSON output
egeria-advisor "What is a collection?" --format=json

# Disable source citations
egeria-advisor --no-citations "Explain governance zones"
```

### 2. Interactive Mode (Multi-turn Conversations)

```bash
egeria-advisor --interactive

# Prompts:
egeria> What is a metadata repository?
egeria> How do I connect to one?
egeria> Show me example code
egeria> /dry-run       # Toggle dry-run for Dr. Egeria commands
egeria> /citations     # Toggle source citations
egeria> /help          # Show all commands
egeria> /exit
```

**Interactive commands:**

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/clear` | Clear conversation context |
| `/history` | Show recent query history |
| `/verbose` | Toggle verbose output |
| `/citations` | Toggle source citations |
| `/dry-run` | Toggle Dr. Egeria dry-run (compose commands without executing) |
| `/feedback` | Provide feedback on last response |
| `/stats` | Show feedback statistics |
| `/exit` | Exit (also Ctrl+D) |

### 3. Agent Mode (Conversational with Memory)

```bash
egeria-advisor --agent

# Agent maintains conversation history across turns:
egeria> I need to create a glossary
egeria> What parameters do I need?
egeria> Show me the complete code
egeria> /tools         # List available MCP tools
egeria> /execute       # Execute an MCP tool directly
egeria> /exit
```

### 4. Action Queries (Dr. Egeria)

Natural-language requests classified as `command` type are handled by the DrEgeriaActionAgent.
It finds the appropriate Dr. Egeria markdown template and composes the command with your parameters.

```bash
# Direct action query
egeria-advisor "Create a glossary called 'Data Governance Terms'"

# In interactive mode with dry-run (preview without executing)
egeria> /dry-run
egeria> Create a project called 'Data Quality Initiative'
```

### 5. Monitoring & Incremental Updates

```bash
# Start real-time monitoring dashboard
python -m advisor.dashboard.terminal_dashboard

# Detect changes in a collection (dry-run)
python -m advisor.incremental_indexer --collection pyegeria --dry-run

# Apply incremental updates to a collection
python -m advisor.incremental_indexer --collection pyegeria

# Update all collections
python -m advisor.incremental_indexer --all
```

### 6. Testing

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
```

## Project Structure

```
egeria-advisor/
├── advisor/                    # Main package
│   ├── agents/                 # Agent implementations
│   │   ├── pyegeria_agent.py   # Python SDK query agent
│   │   ├── dr_egeria_agent.py  # Action agent (Dr. Egeria commands)
│   │   └── ...
│   ├── cli/                    # CLI interface
│   │   ├── main.py             # Entry point and direct-query handler
│   │   ├── interactive.py      # Interactive REPL session
│   │   └── formatters.py       # Response formatting
│   ├── data_prep/              # Data preparation pipeline
│   ├── vector_store_base.py    # Abstract base class for vector backends
│   ├── vector_store.py         # Milvus backend (legacy)
│   ├── vector_store_pg.py      # pgvector backend (active)
│   ├── multi_collection_store.py
│   ├── rag_system.py           # Main RAG orchestrator
│   ├── report_pipeline.py      # MCP report pipeline
│   └── collection_config.py    # Collection definitions
├── config/
│   ├── advisor.yaml            # Primary configuration
│   ├── routing.yaml            # Collection routing rules
│   └── report_specs/           # Report specification templates
├── scripts/
│   ├── ingest_collections.py   # Full re-index a collection
│   ├── count_vectors.py        # Count vectors per collection
│   ├── generate_question_specs.py  # Generate report question specs
│   └── ...
├── data/                       # SQLite metrics database
├── tests/                      # Test suite
└── docs/                       # Architecture and design docs
```

## Configuration

Primary config: `config/advisor.yaml`. Key sections:

- **data_sources**: Path to egeria-python and egeria-workspaces repositories
- **pgvector**: PostgreSQL connection (host, port, dbname, user, password)
- **vector_store_backend**: `pgvector` (active) or `milvus` (legacy)
- **llm**: Ollama model selection and parameters per agent type
- **embeddings**: Model, device, batch size
- **rag**: chunk_size, top_k, min_score thresholds
- **observability**: MLflow tracking URI and experiment name

Settings are managed via Pydantic models in `advisor/config.py`.

## Monitoring & Observability

### Terminal Dashboard

```bash
# Start real-time monitoring (5-second auto-refresh)
python -m advisor.dashboard.terminal_dashboard
```

Displays: collection health, recent queries, query performance (latency, cache hits), and system resources.

### MLflow Tracking

MLflow tracking runs in a background daemon thread and does not block query responses.

- **MLflow UI**: <http://localhost:5025>
  - View experiments and runs
  - Compare query performance over time
  - Monitor collection usage patterns

Disable per-query with `--no-track`. Set `mlflow.enabled: false` in `advisor.yaml` to disable globally.

### SQLite Metrics

All query metrics are stored locally in `data/metrics.db` regardless of MLflow status:
- Query text, timestamp, and latency
- Collections searched and result counts
- Cache hit/miss status

## Documentation

### Design & Architecture

- [System Architecture](docs/design/SYSTEM_ARCHITECTURE.md)
- [Multi-Collection Design](docs/design/MULTI_COLLECTION_DESIGN.md)
- [Query Classification & Tracking](docs/design/QUERY_CLASSIFICATION_AND_TRACKING.md)
- [Egeria Docs Split Strategy](docs/design/EGERIA_DOCS_SPLIT_STRATEGY.md)

### Usage Guides

- [Quick Start](docs/user-docs/quick-start-guide.md)
- [Multi-Collection Usage Guide](docs/user-docs/MULTI_COLLECTION_USAGE_GUIDE.md)
- [Query Routing Guide](docs/user-docs/QUERY_ROUTING_GUIDE.md)
- [MLflow Enhanced Tracking](docs/user-docs/MLFLOW_ENHANCED_TRACKING.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

```bash
# Development setup
source activate_venv.sh
pip install -e ".[dev]"

# Format and lint
black advisor/
ruff check advisor/
mypy advisor/

# Run tests
python scripts/test_end_to_end.py --quick
```

## Support

- **Project Lead**: <dan.wolfson@pdr-associates.com>
- **Egeria Community**: <http://egeria-project.org/guides/community/>
- **Issues**: <https://github.com/odpi/egeria-python/issues>
- **Slack**: #egeria-python on LF AI & Data Slack

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.
