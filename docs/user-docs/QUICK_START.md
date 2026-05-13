# Egeria Advisor — Quick Start

**Last Updated:** 2026-05-13

Get the web UI running and ask your first question in under five minutes.

---

## Prerequisites

Ensure these services are running before you start:

| Service | Default location | Required for |
|---|---|---|
| PostgreSQL + pgvector | `localhost:5442` | All queries (vector store) |
| Ollama | `localhost:11434` | LLM generation |
| Egeria / pyegeria MCP server | `localhost:9443` | Report and action queries only |
| MLflow | `localhost:5025` | Optional — experiment tracking |

```bash
# Check Ollama
curl http://localhost:11434/api/tags

# Check pgvector
psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c "SELECT COUNT(*) FROM pyegeria;"

# Check Egeria (if using reports or actions)
curl -k https://localhost:9443/open-metadata/platform-services/users/garygeeke/server-platform/origin
```

---

## Start the Web UI

```bash
cd /Users/dwolfson/localGit/egeria-v6/egeria-advisor
source activate_venv.sh
uvicorn advisor.web.app:app --reload
```

Open **http://localhost:8000** in your browser.

---

## UI Layout

```
┌──────────────────────────────────────────────────────────────┐
│  [Logo]  Egeria Advisor                           ●          │  ← Header (● = MCP status)
├───────────────────┬──────────────────────────────────────────┤
│  Available        │                                          │
│  Reports          │  [chat messages appear here]             │
│  ▶ Glossary       │                                          │
│  ▶ Governance     │                                          │
│  ▶ Projects       │  ─────────────────────────────────────  │
│  ▶ ...            │  As:  Anyone  Developer  Data Engineer   │
│  ───────────────  │        Steward  Governance               │
│  Recent Queries   │  Intent: Auto  Explain  Show me          │
│                   │          Report  Act  Troubleshoot        │
│                   │  [Enter your question...]       [Send]   │
└───────────────────┴──────────────────────────────────────────┘
```

**Left sidebar:** Reports grouped by topic — click any report to open the Run modal.  
**As:** row: select your role (affects routing and response framing).  
**Intent:** row: override automatic query classification.

---

## Your First Five Queries

Try these in order to see each capability:

### 1. Conceptual explanation (Anyone, Auto)
```
What is a governance zone?
```
*→ Explanation from indexed Egeria documentation*

### 2. Live report (Anyone, Report — or click from sidebar)
```
List available glossaries
```
*→ Live data table from your Egeria instance*

### 3. Python API reference (set role to Developer, Auto)
```
What methods are available for governance definitions?
```
*→ Structured table: GovernanceOfficer class, method names, signatures*

### 4. Runnable code example (Developer, Auto or Show me)
```
Give me a python example to create a governance zone
```
*→ Complete Python script using GovernanceOfficer.create_governance_definition with GovernanceZoneProperties body*

### 5. Dr.Egeria template (set role to Data Steward, Act)
```
Show me a Dr.Egeria template for creating a glossary
```
*→ Markdown template to paste into an Egeria Workspaces Jupyter cell*

---

## Role and Intent Quick Reference

**Role selector (As:)**

| Role | When to use |
|---|---|
| **Anyone** | General questions, live data, conceptual explanations |
| **Developer** | Python code examples, API discovery, integration work |
| **Data Engineer** | Pipeline, connector, ingestion queries — same code routing as Developer |
| **Data Steward** | Dr.Egeria templates, glossary management, data quality — ambiguous "show me" queries ask whether you want Python or a template |
| **Governance** | Policy, compliance, governance zone management — same clarification behaviour as Data Steward |

**Intent selector**

| Button | Use when |
|---|---|
| **Auto** | Default — role + query signals determine the route |
| **Explain** | You want a concept explained, not code or data |
| **Show me** | Force Python code / API reference (even without Developer role) |
| **Report** | Force live data from your Egeria instance |
| **Act** | Force Dr.Egeria command template or execution |
| **Troubleshoot** | You're diagnosing an error |

---

## Common Query Patterns

See **[Prompt Patterns Guide](PROMPT_PATTERNS_GUIDE.md)** for a comprehensive set of examples by role and intent. A brief summary:

| I want… | Role | Intent | Example query |
|---|---|---|---|
| Concept explanation | Anyone | Explain | "What is a governance zone?" |
| Live Egeria data | Anyone | Report | "List all governance zones" |
| Python code example | Developer | Auto | "Python example to create a glossary term" |
| API method list | Developer | Show me | "What methods does GovernanceOfficer have?" |
| Dr.Egeria template | Data Steward | Act | "Dr.Egeria template for creating a project" |
| Execute an action | Data Steward | Act | "Create a governance zone called Finance" |
| Debug an error | Developer | Troubleshoot | "Why am I getting 403 on create_governance_definition?" |

---

## Running Reports from the Sidebar

1. Click any report name in the left panel
2. Optionally enter a **Search string** to filter (e.g., `finance`)
3. Click **Run**

The result is rendered as a markdown table in the chat. The sidebar always forces `Report` intent regardless of which intent button is currently selected.

---

## CLI Alternative

```bash
# One-shot query
egeria-advisor "What is a glossary term in Egeria?"

# Interactive multi-turn session
egeria-advisor --interactive

# Agent mode (BeeAI conversational memory)
egeria-advisor --agent
```

---

## If Something Isn't Working

| Symptom | Fix |
|---|---|
| Getting a report instead of code | Add "python" to your query, or use Show me intent |
| Getting code instead of a report | Use Report intent, or click the report in the sidebar |
| Getting a clarification (Python vs Dr.Egeria?) | Set intent explicitly: Show me for code, Act for template |
| Response mentions methods that don't exist | Include the class name: "using GovernanceOfficer" |
| MCP dot is red | Egeria server not reachable — report and action queries won't work |
| "No relevant content found" | Check that collections are indexed: `python scripts/count_vectors.py` |

See **[Query Routing Guide](QUERY_ROUTING_GUIDE.md)** for detailed routing behaviour and troubleshooting.
