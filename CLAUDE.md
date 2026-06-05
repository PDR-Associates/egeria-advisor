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
User Query  [+ optional perspective + optional intent_override]
  → Web UI (advisor/web/static/index.html)    ← browser SPA
  → FastAPI (advisor/web/app.py)               ← /api/query
  → RAGSystem (advisor/rag_system.py)          ← main orchestrator
      ├─ QueryCache (advisor/query_cache.py)    ← checked first; large speedup on hits
      ├─ QueryProcessor (advisor/query_processor.py)  ← pattern-match classifier (routing.yaml)
      │    └─ if 'general': LLMIntentClassifier ← zero-temp LLM call → refined intent
      │                      (LIVE_DATA/CODE_HELP/CONCEPT/WRITE_COMMAND/AMBIGUOUS)
      │
      ├─ Role-aware routing (before pipeline dispatch, skipped when intent_override set)
      │    ├─ developer|data_engineer + code/example/method signals
      │    │    → ExamplesAgent (advisor/agents/examples_agent.py)
      │    └─ data_steward|governance_officer + ambiguous example signals (no python keyword)
      │         → clarification response (Python vs Dr.Egeria)
      │
      ├─ quantitative  → Analytics module (direct SQL answer)
      ├─ relationship  → RelationshipQueryHandler
      ├─ report        → ReportPipeline (advisor/report_pipeline.py) via MCP
      │                  ← semantic pre-check (_is_report_query, threshold 0.50)
      │                  ← blocked when _CODE_EXAMPLE_SIGNALS present in query
      ├─ command (+ template/sample/example keyword)
      │    → DrEgeriaTemplateAgent (advisor/agents/dre_template_agent.py)
      │      ← filesystem lookup: {EGERIA_ROOT_PATH}/Templates/Dr-Egeria-Templates/{level}/
      ├─ command (no template keyword)
      │    → DrEgeriaActionAgent (advisor/agents/dr_egeria_agent.py)
      ├─ code_search|example → ExamplesAgent (BeeAI + direct-retrieval fallback)
      │    ├─ method-discovery queries ("what methods", "what api", "list methods", …)
      │    │    → API reference mode: returns structured class/method table
      │    └─ code-example queries → runnable Python example (canonical pattern)
      ├─ explanation|best_practice|comparison|debugging|general
      │    → DocAgent (advisor/agents/doc_agent.py)
      └─ fallback → RAG retrieval + LLM generation
           ├─ CollectionRouter (advisor/collection_router.py)
           ├─ MultiCollectionStore (advisor/multi_collection_store.py)
           │    └─ pgvector (HNSW index, 384-dim sentence-transformer embeddings)
           ├─ LLMClient (advisor/llm_client.py)
           └─ PromptTemplates (advisor/prompt_templates.py)
                └─ perspective addendum injected into system prompt when set
```

MLflow tracking runs in a background daemon thread after `query()` returns — it does not block the CLI response.

### Web UI (`advisor/web/`)

Single-page app served by FastAPI at `http://localhost:8880` (default port).

```bash
# Start the web UI
python -m advisor.web.app
# or
uvicorn advisor.web.app:app --reload
```

**Layout:**
- **Header**: Egeria logo + "Egeria Advisor" title + MCP status dot (green = connected, red = disconnected)
- **Left sidebar** (top): Available Reports grouped by topic — click any report to open the run modal
- **Left sidebar** (bottom): Recent Queries — click to restore a query
- **Chat area**: markdown-rendered Q&A with source citations and 👍/👎 feedback
- **Input area**:
  - **As:** perspective selector — Anyone / Developer / Data Engineer / Data Steward / Governance
  - **Intent:** Auto / Explain / Show me / Report / Act / Troubleshoot

**Report modal**: Opens when a report is clicked from the sidebar. The *Search string* field is passed as `search_string` to the MCP `run_report` tool (leave blank for all records, or enter a filter like `finance`).

**Perspective selector**: Stores the selected role and sends it with every query. The backend injects a role-specific addendum into the system prompt and tags the user message with `[User role: ...]`, so the LLM adjusts the depth, terminology, and focus of its response accordingly.

**API endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | index.html |
| POST | `/api/query` | Run query; accepts `query`, `intent_override`, `search_string`, `perspective` |
| GET | `/api/reports` | Report catalog by topic |
| GET | `/api/status` | MCP server connection status |
| POST | `/api/feedback` | Record 👍/👎 |

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

| Agent | File | Handles |
|---|---|---|
| `DrEgeriaActionAgent` | `dr_egeria_agent.py` | `command` queries — composes and executes Dr.Egeria pyegeria commands via MCP |
| `DrEgeriaTemplateAgent` | `dre_template_agent.py` | `command` + template/sample/example keyword — returns pre-generated Dr.Egeria markdown templates from the filesystem |
| `ExamplesAgent` | `examples_agent.py` | `code_search` / `example` — generates runnable pyegeria code examples *or* structured API-reference listings (method-discovery mode) |
| `DocAgent` | `doc_agent.py` | `explanation` / `best_practice` / `comparison` / `debugging` / `general` — conceptual answers from indexed docs |
| `ConversationAgent` | `conversation_agent.py` | Multi-turn sessions (BeeAI framework) |
| `CLICommandAgent` | `cli_command_agent.py` | hey_egeria CLI command lookup and generation |

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

### Report Pipeline Design Rules

1. **Direct dispatch normalises the report name** — `ReportPipeline._resolve_report_name()` strips spaces, hyphens, and underscores and lowercases before comparing, so "IntegrationConnectors" resolves to "Integration Connectors". Call it before invoking the MCP, not after.

2. **Distinguish MCP connection failure from report-not-found** — `_execute_report` calls `_ensure_agent()` before `run_report()`. If `_ensure_agent` raises `ConnectionError` the response says "MCP server not reachable". If the agent connected but `run_report` returned `None` (tool error, unknown report name), the response says "report not found or failed to execute" — never blame the server for a missing report.

3. **`_dict_to_markdown_table` handles three dict shapes**: (a) `{name: {props...}}` — one row per name with flattened columns; (b) `{key: [records...]}` — the list is unwrapped and rendered as a standard data table; (c) `{key: scalar}` — rendered as a Property/Value table. This covers the common pyegeria DICT output format of `{"Report Title": [{...}, ...]}`.

4. **Perspective flows end-to-end**: Web UI → `QueryRequest.perspective` → `RAGSystem.query()` → `_process_query()` → `ReportPipeline.process()` (used by `QuestionSpecIndex.search()` to filter specs) and also into `PromptTemplateManager.get_system_prompt()` which appends a role-specific addendum.

5. **`QuestionSpecIndex.search()` perspective filter** zeros out scores for specs whose `perspectives` list does not contain the selected role (or `"any"`). A `None` perspective disables filtering — all specs are eligible.

### Agent & Routing Design Rules

6. **BeeAI `FunctionTool` objects (produced by `@tool`) have no `.func` attribute** — calling `my_tool.func(...)` raises `AttributeError`. Extract implementation into a `_<name>_raw()` plain function; the `@tool` wrapper delegates to it. Fallback methods import and call the raw function directly. See `_find_dre_template_raw`, `_search_egeria_content_raw`, `_get_egeria_symbol_raw` in `advisor/agents/tools.py`.

7. **Gate ExamplesAgent on `"```python" in response`** (not just `"```"`), so inline-backtick plain-text responses still fall through to the direct-retrieval fallback. Method-discovery (API-reference) mode gates on `"##" in response or "| Method |" in response`.

8. **`_is_report_query` is guarded by `_CODE_EXAMPLE_SIGNALS`** — if the query contains "python", "code example", "pyegeria example", etc., the semantic similarity check is skipped entirely so code-example queries are never mistakenly sent to the MCP report pipeline.

9. **LLM intent classifier (`advisor/llm_intent_classifier.py`) maps `CODE_HELP` → `code_search`** — "python", "example", "sample", "code", "how do I", "write a" all trigger CODE_HELP even when the topic involves creating/updating objects. Only pure imperative commands with no code qualifier map to WRITE_COMMAND.

10. **Dr.Egeria template lookup uses `_templates_root()`** which tries two layouts in order: `{root}/Templates/Dr-Egeria-Templates` (workspace layout) then `{root}/templates` (lower-case fallback). The root comes from `pyegeria.core.config.get_app_config().Environment.pyegeria_root` first, then `EGERIA_ROOT_PATH` / `PYEGERIA_ROOT_PATH` env vars.

11. **Role-aware routing in `_process_query`** fires *before* pipeline dispatch and is skipped when `query_type_override` is set. Developer/Data Engineer + code/example/method-discovery signals → always route to ExamplesAgent. Data Steward/Governance + ambiguous example signals (no Python keyword) → return a clarification asking whether they want Python code or a Dr.Egeria template.

12. **`routing.yaml` CRITICAL priority patterns** are checked before HIGH/MEDIUM patterns. Python/code example patterns in CRITICAL `example` ensure "give me a python example to create X" is classified before it can match HIGH `command` or `report` patterns. Method-discovery patterns ("what methods", "what api", "list methods", etc.) are CRITICAL `code_search` so they never fall to `general`.

## Code Style

Black + Ruff for formatting/linting, MyPy for type checking. Configured in `pyproject.toml`.

```bash
black advisor/
ruff check advisor/
mypy advisor/
```
