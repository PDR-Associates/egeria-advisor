"""Examples agent — generates complete, runnable pyegeria code examples.

Also handles API-reference / method-discovery queries ("what methods are
available for X?") using a separate prompt mode that returns a structured
listing rather than a runnable code example.
"""
from __future__ import annotations

import re

from loguru import logger

from advisor.agents.base import BaseAdvisorAgent

# pyegeria collections that contain code and functional/scenario tests
_CODE_COLLECTIONS = ["pyegeria", "pyegeria_cli"]
_EXAMPLE_COLLECTIONS = ["pyegeria", "pyegeria_cli", "egeria_general"]

# Phrases that indicate the user wants a method listing, not a code example.
_METHOD_DISCOVERY_SIGNALS = (
    "what methods",
    "which methods",
    "list methods",
    "available methods",
    "what api",
    "available api",
    "what functions",
    "list functions",
    "what can i do with",
    "what operations",
    "available operations",
    "what does the",
    "what class",
    "which class",
    "what pyegeria",
    "api reference",
    "api for",
    "methods for",
    "methods to",
)

# Canonical pyegeria code pattern — injected into every prompt so the LLM
# does not invent its own connection / auth approach.
_PATTERN_GUIDE = """\
## Canonical pyegeria Code Pattern

Every pyegeria example MUST follow this exact structure:

```python
import json
import os
from pyegeria import <ClassName>               # top-level re-export preferred
from pyegeria.core._exceptions import PyegeriaException, print_basic_exception
from rich.console import Console

console = Console(width=200)

# --- Client setup: CHOOSE ONE ---

# Option A – explicit parameters (use when you want to be specific):
client = <ClassName>(
    view_server="YOUR_VIEW_SERVER",    # e.g. "qs-view-server"; EGERIA_VIEW_SERVER env var
    platform_url="YOUR_PLATFORM_URL",  # e.g. "https://localhost:9443"; EGERIA_PLATFORM_URL
    user_id="YOUR_USER_ID",            # EGERIA_USER env var
    user_pwd="YOUR_PASSWORD",          # EGERIA_USER_PASSWORD env var
)

# Option B – zero-argument (reads EGERIA_VIEW_SERVER / EGERIA_PLATFORM_URL /
#            EGERIA_USER / EGERIA_USER_PASSWORD from .env or OS environment):
# client = <ClassName>()

# --- Authentication ---
token = client.create_egeria_bearer_token()   # uses env vars; or pass (user, password) explicitly

try:
    # --- API call (show at minimum the required params; document optional ones) ---
    response = client.<method>(
        required_param,
        optional_param=default_value,   # document what it does
    )

    # --- Output rendering ---
    if isinstance(response, list):
        print(f"Found {len(response)} items")
        print(json.dumps(response, indent=2))
    elif isinstance(response, str):
        console.print(response)
    else:
        console.print(response)

except PyegeriaException as e:
    print_basic_exception(e)
finally:
    client.close_session()
```

Rules:
- ALWAYS include both Option A (explicit) and Option B (zero-arg) constructor forms.
- ALWAYS call `create_egeria_bearer_token()` before any API method.
- ALWAYS wrap in try/except PyegeriaException / finally close_session().
- Use ONLY class names, method names, and parameter names you found in the retrieved context.
- Document EVERY parameter with a short inline comment — at minimum the ones shown above.
- The canonical import is `from pyegeria import <ClassName>`.
  If the class is not re-exported from `pyegeria.__init__`, fall back to the module path
  you found in the retrieved context (e.g. `from pyegeria.omvs.governance_officer import GovernanceOfficer`).
- Use CLEARLY LABELLED placeholders: `YOUR_VIEW_SERVER`, `YOUR_PLATFORM_URL`, `YOUR_USER_ID`, `YOUR_PASSWORD`.
- **CRITICAL — Never invent methods.** If you cannot find a method verbatim in the retrieved
  context, say "I could not find the API for this in the indexed content" and stop.
- After the code block add a 3–5 sentence explanation covering: what the example does,
  which constructor option to prefer, and what output to expect.

## Egeria Unified Definition API Pattern (CRITICAL)

Egeria uses a UNIFIED creation API: many object types share a single method, with the
type specified in the request body via `typeName` — there is NO separate per-type create method.

**DO NOT generate:**  `create_governance_zone()`, `create_governance_principle()`,
`create_business_imperative()`, `create_certification_type()`, etc.
**These methods do not exist.**

**DO generate** (when the retrieved context confirms it):
```python
body = {
    "class": "NewElementRequestBody",
    "properties": {
        "class": "GovernanceZoneProperties",   # or GovernanceDefinitionProperties, etc.
        "typeName": "GovernanceZone",           # the actual Egeria type
        "qualifiedName": client.__create_qualified_name__("GovernanceZone", display_name),
        "displayName": display_name,
        "description": "...",
        "domainIdentifier": 0,                 # 0 = all domains
    }
}
guid = client.create_governance_definition(body)
```

The property class name to use per type is documented in the `GovernanceOfficer.create_governance_definition`
docstring (visible in the retrieved context). Always show the body structure, not just the method call.
"""


_API_REF_SYSTEM_PROMPT = """\
You are an expert pyegeria developer. The user wants to discover what pyegeria \
classes and methods are available for a topic — NOT a runnable code example.

Workflow:
1. Call search_egeria_content with the user's topic against collection 'pyegeria' \
to find relevant classes.
2. ALSO call search_egeria_content with "class method create <topic>" against 'pyegeria' \
to find method signatures that may not appear in a plain topic search.
3. For each class you find, call get_egeria_symbol with the exact class name to \
retrieve its full method list and signatures.
4. Return a structured reference in this format:

## <ClassName>
**Module**: `from pyegeria.omvs.<module> import <ClassName>`
**Purpose**: one-sentence description.

| Method | Signature | Description |
|--------|-----------|-------------|
| `method_name` | `(param1, param2=default)` | what it does |

Repeat for every relevant class you find.

CRITICAL rules:
- List ONLY classes and methods that appear VERBATIM in the retrieved context.
- Do NOT invent method names. If `create_governance_zone()` does not appear in the \
  context, do NOT list it.
- Egeria uses a UNIFIED definition API: many types share one method, with the type \
  specified as `typeName` in the request body. For example, GovernanceZone, \
  GovernancePrinciple, and GovernanceObligation are all created via \
  `GovernanceOfficer.create_governance_definition(body)` — there is no separate \
  `create_governance_zone()` method. When you see this pattern, say so clearly and \
  show the body structure as a code snippet.
- Do NOT generate a runnable code example — the user wants a reference listing.
- If the context does not contain enough information, say so rather than guessing.
"""


class ExamplesAgent(BaseAdvisorAgent):
    def __init__(self):
        self._api_ref_mode = False

    def system_prompt(self) -> str:
        if self._api_ref_mode:
            return _API_REF_SYSTEM_PROMPT
        return (
            "You are an expert pyegeria developer who writes clear, complete, runnable Python "
            "code examples for the Egeria metadata platform SDK.\n\n"
            "Workflow:\n"
            "1. Call search_egeria_content with the user's topic against collection 'pyegeria' "
            "to find the relevant class (e.g. GlossaryManager, DataDesigner).\n"
            "2. Search again with a test-oriented query such as 'functional test <ClassName>' "
            "or 'test_<method>' against collection 'pyegeria' to find the functional tests "
            "that show the real constructor arguments and method call patterns.\n"
            "3. Call get_egeria_symbol for the exact class name to confirm its signature.\n"
            "4. Generate a complete Python example that follows the canonical pattern below.\n\n"
            + _PATTERN_GUIDE
        )

    def tools(self) -> list:
        from advisor.agents.tools import search_egeria_content, get_egeria_symbol
        return [search_egeria_content, get_egeria_symbol]

    @staticmethod
    def _is_method_discovery(query: str) -> bool:
        q = query.lower()
        return any(sig in q for sig in _METHOD_DISCOVERY_SIGNALS)

    def handle(self, query: str) -> dict:
        if self._is_method_discovery(query):
            logger.info("ExamplesAgent: method-discovery mode")
            return self._handle_api_reference(query)

        # Direct retrieval + single LLM call — BeeAI ReAct loop skipped because
        # each Ollama round-trip costs 30-90s and the multi-turn loop adds no value
        # over the structured retrieval below with a local 8B model.
        logger.info("ExamplesAgent: direct retrieval path")
        return _make_result(query, self._fallback(query), "example")

    def _handle_api_reference(self, query: str) -> dict:
        """Return a structured method-reference listing rather than a code example."""
        logger.info("ExamplesAgent: direct API reference retrieval")
        return _make_result(query, self._fallback_api_reference(query), "code_search")

    def _fallback_api_reference(self, query: str) -> str:
        """Fallback: retrieve pyegeria source chunks and ask the LLM to format a reference."""
        from advisor.agents.tools import _search_egeria_content_raw, _get_egeria_symbol_raw
        from advisor.llm_client import get_ollama_client

        # Pass 1: topic search
        context_topic = _search_egeria_content_raw(query, ["pyegeria"], top_k=6)
        # Pass 2: targeted class/method search to find signatures not in topic search
        context_methods = _search_egeria_content_raw(
            f"create definition method body {query}", ["pyegeria"], top_k=5
        )
        context = context_topic
        if context_methods and context_methods != "No relevant content found.":
            context += "\n\n--- Targeted method search ---\n" + context_methods

        if not context or context == "No relevant content found.":
            return (
                "I couldn't find pyegeria classes matching that topic in my index. "
                "Try naming a specific class (e.g. 'GovernanceOfficer') or concept "
                "(e.g. 'governance definition', 'glossary', 'project')."
            )

        # Pass 3: for every class name found in the retrieved chunks, call get_egeria_symbol
        # to get the full method list — this is the ground-truth source.
        class_names = _extract_class_names(context)
        for cls in class_names[:3]:
            sym = _get_egeria_symbol_raw(cls)
            if sym and "No symbol found" not in sym:
                context += f"\n\n--- Symbol lookup: {cls} ---\n{sym}"
        if len(context) > 8000:
            context = context[:8000] + "\n...[truncated]"

        system = (
            "You are an expert pyegeria developer producing an API reference for a user.\n\n"
            "STRICT RULES:\n"
            "1. List ONLY classes and methods that appear VERBATIM in the retrieved context below.\n"
            "2. Do NOT invent method names. If a method like `create_governance_zone()` does NOT "
            "appear in the context, do NOT include it — even if it sounds reasonable.\n"
            "3. If Egeria uses a unified method (e.g. `create_governance_definition(body)`) with "
            "a `typeName` in the body to distinguish object types, say so explicitly and show "
            "the body structure — do NOT invent separate per-type methods.\n"
            "4. Format as markdown: ## ClassName, then a table "
            "| Method | Parameters | Description | for each class.\n"
            "5. If the context does not contain enough information, say so rather than guessing."
        )
        user_prompt = (
            f"The user asked: {query}\n\n"
            f"Retrieved pyegeria source context — use ONLY what appears here:\n{context}\n\n"
            "List the relevant classes and methods. For each method show its exact signature "
            "and a one-line description from the docstring. "
            "If the context shows a body dict structure (e.g. for create_governance_definition), "
            "include that structure as a code snippet — it is the essential usage detail."
        )
        try:
            return get_ollama_client().generate(user_prompt, system=system, max_tokens=2000)
        except Exception as exc:
            return f"Could not retrieve API reference: {exc}"

    def _fallback(self, query: str) -> str:
        from advisor.agents.tools import _search_egeria_content_raw, _get_egeria_symbol_raw
        from advisor.llm_client import get_ollama_client

        # Pass 1: topic search — finds general context for the concept
        context_api = _search_egeria_content_raw(query, _EXAMPLE_COLLECTIONS, top_k=6)
        # Pass 2: functional test search — finds real constructor + body patterns
        context_tests = _search_egeria_content_raw(
            f"functional test {query}", _EXAMPLE_COLLECTIONS, top_k=5
        )
        # Pass 3: targeted method/body search — finds creation method even when
        # user phrasing ("governance zone") differs from the indexed method name
        context_methods = _search_egeria_content_raw(
            f"create definition method body {query}", ["pyegeria"], top_k=4
        )
        context = context_api
        if context_tests and context_tests != "No relevant content found.":
            context += "\n\n--- Functional test examples ---\n" + context_tests
        if context_methods and context_methods != "No relevant content found.":
            context += "\n\n--- Method signatures ---\n" + context_methods

        # Pass 4: extract class names found so far and look up their symbols —
        # ensures we have the authoritative method list before synthesis.
        class_names = _extract_class_names(context)
        for cls in class_names[:2]:
            sym = _get_egeria_symbol_raw(cls)
            if sym and "No symbol found" not in sym:
                context += f"\n\n--- Symbol lookup: {cls} ---\n{sym}"

        if len(context) > 10000:
            context = context[:10000] + "\n...[truncated]"

        system = (
            "You are an expert pyegeria developer. Write a complete, runnable Python code example "
            "based ONLY on the retrieved context below. "
            "You MUST follow the canonical pattern exactly as specified.\n\n"
            + _PATTERN_GUIDE +
            "\nSTRICT: Use ONLY the class names, imports, and method signatures that appear "
            "VERBATIM in the context. If the context shows `create_governance_definition(body)`, "
            "use that — do NOT invent `create_governance_zone()` or any other non-existent method. "
            "If you cannot find the right method in the context, say so explicitly rather than "
            "inventing one. Your response MUST contain a fenced ```python code block."
        )
        user_prompt = (
            f"Write a complete Python code example for: {query}\n\n"
            f"Retrieved context — use ONLY these imports, class names, method signatures, "
            f"and body structures:\n{context}\n\n"
            f"Follow the canonical pattern: both constructor options, "
            f"create_egeria_bearer_token(), try/except/finally, output rendering. "
            f"Show the full body dict if the method takes one. "
            f"Document every parameter with an inline comment."
        )
        try:
            return get_ollama_client().generate(user_prompt, system=system, max_tokens=2500)
        except Exception as exc:
            return (
                f"Could not generate an example for this query: {exc}\n\n"
                "Try rephrasing or check that pyegeria is indexed."
            )


def _extract_class_names(context: str) -> list[str]:
    """
    Parse class names out of formatted retrieval context.

    Each chunk is formatted as:
        [collection | file | score=N]
        Name: X
        Type: class | method | function
        Class: Y          ← present on method chunks

    Returns class names for classes found, plus the parent class of any method chunks.
    """
    names: list[str] = []
    for chunk in context.split("---"):
        # Method chunks include "Class: ClassName"
        m = re.search(r'\bClass:\s+(\w+)', chunk)
        if m:
            names.append(m.group(1))
        # Class chunks: "Name: X" where "Type: class" follows
        if re.search(r'\bType:\s+class\b', chunk):
            m = re.search(r'\bName:\s+(\w+)', chunk)
            if m:
                names.append(m.group(1))
    return list(dict.fromkeys(names))   # deduplicate, preserve order


def _make_result(query: str, response: str, query_type: str) -> dict:
    return {
        "query": query,
        "response": response,
        "query_type": query_type,
        "sources": [],
        "num_sources": 0,
        "retrieval_time": 0.0,
        "generation_time": 0.0,
        "avg_relevance_score": 0.0,
        "context_length": len(response),
    }


_agent: ExamplesAgent | None = None


def get_examples_agent() -> ExamplesAgent:
    global _agent
    if _agent is None:
        _agent = ExamplesAgent()
    return _agent
