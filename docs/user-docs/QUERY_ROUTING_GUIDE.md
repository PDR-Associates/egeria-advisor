# Egeria Advisor Query Routing Guide

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