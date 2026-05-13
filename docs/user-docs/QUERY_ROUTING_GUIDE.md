# Egeria Advisor Query Routing Guide

**Last Updated:** 2026-05-13

## Overview

Egeria Advisor routes every query through a multi-layer classification pipeline before touching the vector store or any external service. Understanding how routing works helps you phrase questions to get the best results, and helps developers understand where to look when routing misbehaves.

---

## Routing Pipeline (in order)

```
Query + perspective + intent_override
  │
  ├─ 1. QueryCache            ← cache hit → return immediately
  │
  ├─ 2. QueryProcessor        ← pattern match against routing.yaml (CRITICAL → HIGH → MEDIUM → LOW)
  │       └─ if 'general': LLM intent classifier → refined intent
  │
  ├─ 3. Role-aware routing    ← fires before pipeline; skipped when intent_override is set
  │
  └─ 4. Pipeline dispatch     ← sends to the right agent or RAG path
```

---

## Layer 1 — Pattern Matching (`config/routing.yaml`)

Patterns are checked in priority order. The **first match wins**; lower-priority patterns are ignored.

| Priority | Intent types covered |
|---|---|
| **CRITICAL** | `example` (Python code requests), `code_search` (method discovery, how-to navigation), `quantitative`, `debugging`, `best_practice`, `comparison` |
| **HIGH** | `report` (explicit run/show/list commands), `command` (Dr.Egeria create/update/link/set) |
| **MEDIUM** | `code_search` (broad show-me/how-to), `example`, `relationship`, `explanation` |
| **LOW** | `code_search`, `explanation`, `general` |

### CRITICAL patterns that matter most

**Python/code example requests** (`example` intent) — fire before any command or report pattern:
- `"python example"`, `"write python"`, `"give me a python"`, `"show me python"`
- `"python code example"`, `"python code for"`, `"python snippet"`
- `"give me an example"`, `"give me a code"`, `"code example for"`, `"code sample for"`

**Method/API discovery** (`code_search` intent) — fire before generic patterns:
- `"what methods"`, `"which methods"`, `"list methods"`, `"available methods"`
- `"what api"`, `"available api"`, `"api for"`, `"api reference"`
- `"what functions"`, `"list functions"`, `"what operations"`
- `"what can i do with"`, `"what class"`, `"which class"`, `"what pyegeria"`
- `"methods for"`, `"methods to"`

---

## Layer 2 — LLM Intent Classifier (`advisor/llm_intent_classifier.py`)

When pattern matching returns `general`, a zero-temperature LLM call refines the intent:

| Category | Maps to intent | Trigger condition |
|---|---|---|
| `LIVE_DATA` | `report` | User wants current data from Egeria right now |
| `CODE_HELP` | `code_search` | Query mentions "python", "example", "sample", "code", "how do I", "how to", "write a" |
| `CONCEPT` | `explanation` | User wants a definition or explanation |
| `WRITE_COMMAND` | `command` | Direct imperative command with **no** python/code/example qualifier |
| `AMBIGUOUS` | `general` | Genuinely unclear |

**Important:** `CODE_HELP` wins over `WRITE_COMMAND` whenever the query contains python/example/code keywords, even if the topic is about creating or updating objects (e.g., *"write a python example to create a governance definition"* → `CODE_HELP`, not `WRITE_COMMAND`).

---

## Layer 3 — Role-Aware Routing

Applied *after* classification but *before* pipeline dispatch. **Skipped when `intent_override` is set from the UI.**

| Role | Signals present | Routing |
|---|---|---|
| `developer` or `data_engineer` | code, example, how-to, or method-discovery keywords | → ExamplesAgent (bypasses pipeline) |
| `data_steward` or `governance_officer` | example/show-me signals, **without** Python keyword | → Clarification response (Python code vs Dr.Egeria template) |
| Any | Python keyword present | Never routed to report pipeline |

---

## Layer 4 — Pipeline Dispatch

| Classified intent | Additional condition | Agent / path |
|---|---|---|
| `quantitative` | — | Analytics module (SQLite) |
| `relationship` | — | RelationshipQueryHandler |
| `report` | semantic score ≥ 0.50 AND no Python keyword | MCP ReportPipeline |
| `command` | query contains "template", "sample", "example", "show me", or "give me" | DrEgeriaTemplateAgent → filesystem `.md` lookup |
| `command` | no template keyword | DrEgeriaActionAgent → MCP command execution |
| `code_search` or `example` | method-discovery signals ("what methods", "what api", …) | ExamplesAgent — **API reference mode** → class/method table |
| `code_search` or `example` | code-example signals | ExamplesAgent — **example mode** → runnable Python |
| `explanation`, `best_practice`, `comparison`, `debugging`, `general` | — | DocAgent → conceptual answer from indexed docs |
| *(fallback)* | — | RAG retrieval + LLM generation |

---

## What to Ask and What You Get Back

### Runnable Python Code Examples

Ask with Python/code keywords:

```
"Give me a python example to create a governance definition"
"Write python code to list all glossaries"
"Show me python code for creating a project"
"Python snippet for searching data assets"
```

You get back a complete, runnable Python script with:
- Both constructor options (explicit params and zero-arg from `.env`)
- `create_egeria_bearer_token()` before any API call
- `try / except PyegeriaException / finally client.close_session()`
- Inline parameter comments

### API Reference / Method Discovery

Ask what's available on a topic:

```
"What methods are available for governance definitions?"
"Which class handles glossary management in pyegeria?"
"What API does pyegeria have for projects?"
"List methods for DataDesigner"
"What pyegeria methods can I use with collections?"
"What functions are available for creating terms?"
```

You get back a structured markdown table: class name, import path, method names, parameters, and one-line docstring descriptions.

### Dr.Egeria Markdown Templates

Ask for the command template you paste into a Jupyter cell:

```
"Show me a Dr.Egeria template for creating a glossary"
"Give me the command template for creating a governance definition"
"Dr.Egeria sample for linking a term"
"Show me the Act template for creating a project"
```

You get back the pre-generated `.md` template content wrapped in a fenced block, plus a short explanation of required vs optional fields.

Templates are read from `{EGERIA_ROOT_PATH}/Templates/Dr-Egeria-Templates/{basic|advanced}/{family}/{command}.md`. They can be regenerated at any time with `generate_md_cmd_templates.py --advanced`.

### Live Egeria Reports

Ask for current data from a running Egeria instance:

```
"List available glossaries"
"Show me all governance zones"
"What collections exist?"
"Run the Glossary Terms report"
```

Or click any report in the left sidebar — the Run modal opens and always forces `intent_override: 'report'` regardless of which intent button is active.

### Conceptual Explanations

Ask open-ended questions about Egeria concepts:

```
"What is a governance zone?"
"How does data lineage work in Egeria?"
"Explain the difference between a glossary and a data dictionary"
"What is the purpose of an Asset Manager OMAS?"
```

These go to DocAgent, which searches `egeria_concepts`, `egeria_general`, `egeria_types`, and `pyegeria`.

---

## Using the Intent Override Buttons

| Button | Forced intent | Best used when |
|--------|-------------|----------------|
| **Auto** | *(classified)* | Default — role + signals determine the route |
| **Explain** | `explanation` | You want a concept explained, not code |
| **Show me** | `code_search` | You want Python code or an API reference listing |
| **Report** | `report` | You want current live data; also used by sidebar |
| **Act** | `command` | You want Dr.Egeria to do something (or give you the command template) |
| **Troubleshoot** | `debugging` | You're diagnosing an error or unexpected behaviour |

---

## Role + Intent Combinations

| Role | Intent | Query type | Result |
|---|---|---|---|
| Developer | Auto | *"give me a python example to create a glossary"* | Runnable pyegeria code |
| Developer | Auto | *"what methods are available for governance?"* | API reference table |
| Developer | Show me | *"create a governance definition"* | Runnable pyegeria code (role override) |
| Data Steward | Auto | *"show me how to create a glossary"* | Clarification: Python or Dr.Egeria? |
| Data Steward | Act | *"show me a template for creating a glossary"* | Dr.Egeria markdown template |
| Anyone | Report | *"list all glossaries"* | MCP report result (live data) |
| Anyone | Auto | *"what is a governance zone?"* | Conceptual explanation |

---

## Code Example Guard (`_CODE_EXAMPLE_SIGNALS`)

The following keywords in a query **block the semantic report pre-check** entirely — these queries are never accidentally routed to the MCP report pipeline even if the topic (e.g. "glossary") normally scores high:

`"python"`, `"code example"`, `"code sample"`, `"write python"`, `"python code"`, `"pyegeria example"`, `"python snippet"`

---

## Troubleshooting Routing

### Query going to the report pipeline instead of ExamplesAgent?

Add "python" to your query: *"give me a **python** example for creating a glossary"*. The `_CODE_EXAMPLE_SIGNALS` guard prevents the semantic report check from running.

### Query going to ExamplesAgent when you want a report?

Click **Report** in the intent bar. The sidebar always forces `intent_override: 'report'` automatically.

### Getting a clarification response instead of code?

Set your role to **Developer** or **Data Engineer** in the **As:** selector. The role-aware routing then sends code/example signals directly to ExamplesAgent without asking.

### Getting a code example when you wanted a Dr.Egeria template?

Click **Act** in the intent bar, then include "template", "sample", or "example" in your query. Or: set role to Data Steward and ask with "show me" — you'll be offered the choice.

### Method-discovery query giving a code example instead of a reference listing?

Use one of the method-discovery phrases: *"what methods are available for…"*, *"list methods for…"*, *"what API does pyegeria have for…"*. These trigger API-reference mode in ExamplesAgent.
**Version:** 2.0 (Phase 2 Multi-Collection)  
**Last Updated:** 2026-02-19

## Overview

Egeria Advisor uses intelligent query routing to search the right collections based on keywords in your query. This guide shows you how to phrase queries to target specific types of content.

## Available Collections

The system manages **9 collections** with **131,402 entities**:

| Collection | Content | Entities | Priority |
|------------|---------|----------|----------|
| **pyegeria** | Python client library | 9,251 | 10 (highest) |
| **pyegeria_cli** | CLI tools (hey-egeria) | 843 | 9 |
| **pyegeria_drE** | Markdown translator | 878 | 8 |
| **egeria_java** | Java implementation | 59,219 | 7 |
| **egeria_docs** | Documentation | 13,692 | 6 |
| **egeria_workspaces** | Examples & demos | 15,939 | 5 |
| code_elements | Legacy Python code | 18,404 | - |
| documentation | Legacy docs | 10,520 | - |
| examples | Legacy examples | 2,656 | - |

## How to Target Specific Collections

### 📚 Documentation (egeria_docs)

**Use these keywords:** `documentation`, `guide`, `tutorial`, `concept`, `reference`, `docs`, `manual`, `walkthrough`

**Example Queries:**
```
✅ "Show me the documentation for Asset Manager OMAS"
✅ "What is the concept of governance zones?"
✅ "Find the tutorial on setting up Egeria"
✅ "Explain the reference architecture"
✅ "Guide to configuring OMAG servers"
✅ "Egeria architecture documentation"
```

**Why it works:** The word "documentation", "guide", "tutorial", etc. triggers the egeria_docs collection.

---

### ☕ Java Code (egeria_java)

**Use these keywords:** `java`, `omas`, `omag`, `omrs`, `ocf`, `oif`, `access-service`, `view-service`, `integration-service`, `governance-server`, `metadata-server`, `repository-proxy`

**Example Queries:**
```
✅ "How to implement OMAS in Java"
✅ "Show me Java REST API implementation"
✅ "OMAG server configuration code"
✅ "Access-service implementation examples"
✅ "Repository-proxy connector code"
✅ "Java implementation of Asset Manager"
```

**Why it works:** Keywords like "java", "omas", "omag" are strong indicators of Java code.

---

### 🐍 Python Code (pyegeria)

**Use these keywords:** `pyegeria`, `python-client`, `rest-client`, `async-client`, `widget`, `python-api`, `python-sdk`, `egeria-client`

**Example Queries:**
```
✅ "How to use pyegeria to create a glossary"
✅ "Python-client examples for Asset Manager"
✅ "Async-client usage patterns"
✅ "Widget implementation in Jupyter"
✅ "Python API for governance zones"
✅ "Egeria-client connection setup"
```

**Why it works:** "pyegeria" and "python" keywords route to Python collections.

---

### 💻 CLI Tools (pyegeria_cli)

**Use these keywords:** `hey-egeria`, `hey_egeria`, `cli`, `command`, `commands`, `command-line`, `terminal`

**Example Queries:**
```
✅ "hey-egeria commands for glossary management"
✅ "CLI usage for creating assets"
✅ "Command-line tools for Egeria"
✅ "Terminal commands for governance"
✅ "hey_egeria configuration"
```

**Why it works:** "cli", "command", "hey-egeria" trigger CLI collection.

---

### 📓 Examples & Demos (egeria_workspaces)

**Use these keywords:** `workspace`, `notebook`, `jupyter`, `example`, `deployment`, `docker`, `kubernetes`, `helm`, `sample`, `demo`

**Example Queries:**
```
✅ "Show me the Coco Pharmaceuticals demo"
✅ "Jupyter notebook for data lineage"
✅ "Docker deployment configuration"
✅ "Kubernetes setup example"
✅ "Sample workspace for governance"
✅ "Demo of metadata management"
```

**Why it works:** "demo", "example", "notebook", "workspace" route to examples.

---

## Query Phrasing Strategies

### Strategy 1: Explicit Content Type

**Pattern:** `[Content Type] + [Topic]`

```
"Documentation on OMAS architecture"     → egeria_docs
"Java code for OMAS implementation"      → egeria_java
"Python example for OMAS client"         → pyegeria
"Jupyter notebook demo for OMAS"         → egeria_workspaces
"CLI commands for OMAS"                  → pyegeria_cli
```

### Strategy 2: Action + Content Type

**Pattern:** `[Action] + [Content Type] + [Topic]`

```
"Show me the guide for..."               → egeria_docs
"Find Java implementation of..."         → egeria_java
"Give me Python code for..."             → pyegeria
"Display the demo of..."                 → egeria_workspaces
```

### Strategy 3: Language-Specific

**Pattern:** `[Language] + [Action] + [Topic]`

```
"Java REST API implementation"           → egeria_java
"Python async client usage"              → pyegeria
"Markdown documentation structure"       → egeria_docs
```

### Strategy 4: Use Case Specific

**Pattern:** `[Use Case] + [Content Type]`

```
"Deployment docker configuration"        → egeria_workspaces
"Tutorial on governance zones"           → egeria_docs
"Implementation of metadata server"      → egeria_java
```

## Common Query Patterns

### ❌ Ambiguous Queries (May Route Incorrectly)

```
❌ "Tell me about Asset Manager"
   → May route to Java (OMAS is a Java term)
   
❌ "How does OMAG work?"
   → May route to Java (OMAG is Java-specific)
   
❌ "What is a glossary?"
   → Routes to all collections (generic term)
```

### ✅ Clear Queries (Route Correctly)

```
✅ "Show me the documentation for Asset Manager"
   → Routes to egeria_docs
   
✅ "Asset Manager Java implementation"
   → Routes to egeria_java
   
✅ "Python example for creating a glossary"
   → Routes to pyegeria
   
✅ "Jupyter notebook demo for glossaries"
   → Routes to egeria_workspaces
```

## Priority-Based Search

When multiple collections match, they're searched in priority order:

1. **pyegeria** (10) - Highest priority for Python queries
2. **pyegeria_cli** (9) - CLI-specific queries
3. **pyegeria_drE** (8) - Markdown processing
4. **egeria_java** (7) - Java implementation
5. **egeria_docs** (6) - Documentation
6. **egeria_workspaces** (5) - Examples and demos

**Example:** Query "Python OMAS client" matches both pyegeria and egeria_java, but pyegeria is searched first due to higher priority.

## Quick Reference Cheat Sheet

| I Want... | Include Keywords | Example Query |
|-----------|-----------------|---------------|
| **Documentation** | documentation, guide, tutorial, concept | "Show me the **guide** for OMAG servers" |
| **Java Code** | java, omas, omag, implementation | "**Java** **OMAS** implementation" |
| **Python Code** | pyegeria, python-client, python-api | "**pyegeria** glossary creation" |
| **Examples/Demos** | demo, sample, notebook, workspace | "**Jupyter notebook** **demo**" |
| **CLI Commands** | hey-egeria, cli, command | "**hey-egeria** **commands**" |
| **Deployment** | docker, kubernetes, helm, deployment | "**Docker** **deployment** config" |

## Advanced Tips

### Tip 1: Combine Multiple Keywords

```
✅ "Java OMAS implementation guide"
   → Searches egeria_java first, then egeria_docs
```

### Tip 2: Use Specific Technical Terms

```
✅ "OMAG server REST API"        → egeria_java (OMAG + REST)
✅ "Async-client connection"     → pyegeria (async-client)
✅ "Repository-proxy connector"  → egeria_java (repository-proxy)
```

### Tip 3: Specify Format

```
✅ "Markdown documentation"      → egeria_docs
✅ "Jupyter notebook"            → egeria_workspaces
✅ "Python script"               → pyegeria
✅ "Java class"                  → egeria_java
```

### Tip 4: Use Action Verbs

```
"Explain..."     → General (searches all)
"Show me..."     → Specific (uses keywords)
"How to..."      → Code-focused (Java/Python)
"Guide to..."    → Documentation
"Demo of..."     → Examples/workspaces
```

## Testing Your Queries

You can test how your query routes using Python:

```python
from advisor.collection_router import get_collection_router

router = get_collection_router()
collections = router.route_query("your query here")
print(f"Routes to: {collections}")
```

**Example:**
```python
>>> router.route_query("Java OMAS implementation")
Routes to: ['egeria_java']

>>> router.route_query("Show me the documentation for OMAS")
Routes to: ['egeria_docs']

>>> router.route_query("Python example for glossaries")
Routes to: ['pyegeria']
```

## Collection Domain Terms Reference

### egeria_docs
`documentation`, `guide`, `tutorial`, `concept`, `reference`, `docs`, `manual`, `walkthrough`

### egeria_java
`java`, `omas`, `omag`, `omrs`, `ocf`, `oif`, `access-service`, `view-service`, `integration-service`, `governance-server`, `metadata-server`, `repository-proxy`, `egeria-core`, `egeria-server`

### pyegeria
`pyegeria`, `python-client`, `rest-client`, `async-client`, `widget`, `egeria-client`, `python-api`, `python-sdk`

### pyegeria_cli
`hey-egeria`, `hey_egeria`, `cli`, `command`, `commands`, `command-line`, `terminal`

### pyegeria_drE
`dr-egeria`, `dr_egeria`, `markdown`, `document-automation`, `markdown-translator`, `dre`

### egeria_workspaces
`workspace`, `notebook`, `jupyter`, `example`, `deployment`, `docker`, `kubernetes`, `helm`, `sample`, `demo`

## Troubleshooting

### Query Not Finding Results?

1. **Check your keywords** - Are you using collection-specific terms?
2. **Be more specific** - Add content type keywords (java, python, documentation)
3. **Try different phrasing** - Use action verbs (show, find, explain)
4. **Check collection status** - Run `python scripts/check_ingestion_status.py`

### Query Routing to Wrong Collection?

1. **Add explicit keywords** - "documentation", "java", "python", etc.
2. **Remove ambiguous terms** - Generic terms match multiple collections
3. **Use priority keywords** - Higher priority collections are searched first

### Want to Search All Collections?

Use generic queries without specific keywords:
```
"What is a glossary?"
"Tell me about Egeria"
"Explain metadata management"
```

## Summary

**Key Takeaway:** Use explicit keywords to route to the right collection!

- Want **docs**? Say "documentation", "guide", "tutorial"
- Want **Java**? Say "java", "omas", "omag"
- Want **Python**? Say "pyegeria", "python-client"
- Want **examples**? Say "demo", "sample", "notebook"
- Want **CLI**? Say "hey-egeria", "command", "cli"

The system is smart, but explicit keywords ensure you get the best results from the right collection!

---

**Need Help?** Check the [Phase 2 Implementation Complete](../history/PHASE2_IMPLEMENTATION_COMPLETE.md) document for technical details.
