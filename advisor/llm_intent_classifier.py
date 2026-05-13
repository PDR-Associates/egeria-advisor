"""
LLM-based intent classifier for ambiguous queries.

Called when pattern matching returns 'general' — uses a zero-temperature LLM
call to reclassify the query into a more specific intent before falling through
to RAG retrieval.
"""

from typing import Optional
from loguru import logger

_SYSTEM_PROMPT = (
    "You are a query classifier for an Egeria metadata platform assistant. "
    "Respond with ONLY a single category name — no explanation, no punctuation."
)

_CLASSIFY_PROMPT = """\
Classify this Egeria assistant query into ONE of these categories:

LIVE_DATA     - user wants CURRENT DATA from Egeria right now (list glossaries, show assets, run a report, what collections exist)
CODE_HELP     - user wants Python/pyegeria CODE EXAMPLES or API usage help — includes any query that mentions "python", "example", "sample", "code", "how do I", "how to", or "write a" even when the topic involves creating something (e.g. "write a python example to create a glossary", "give me a code sample for creating a governance definition")
CONCEPT       - user wants an explanation or definition (what is a glossary, how does lineage work, explain X)
WRITE_COMMAND - user wants to CREATE/UPDATE/DELETE Egeria metadata RIGHT NOW using a Dr.Egeria command — only when there is NO mention of python, code, example, or sample (e.g. "create a glossary called Finance" with no code qualifier)
AMBIGUOUS     - genuinely unclear

IMPORTANT: When the query mentions "python", "example", "sample", "code", "write a", or "how to/do I", always choose CODE_HELP even if the topic is about creating or updating something. Only choose WRITE_COMMAND for direct imperative commands with no code/example qualifier.

Query: "{query}"

Reply with ONLY the category name."""

# Map classifier output → query_type string used by rag_system
_CATEGORY_TO_QUERY_TYPE = {
    "LIVE_DATA": "report",
    "CODE_HELP": "code_search",
    "CONCEPT": "explanation",
    "WRITE_COMMAND": "command",
    "AMBIGUOUS": "general",
}

_VALID_CATEGORIES = set(_CATEGORY_TO_QUERY_TYPE.keys())


class LLMIntentClassifier:
    """Thin wrapper that classifies a query string via a single LLM call."""

    def __init__(self):
        self._client = None  # lazy — avoid import-time Ollama connection

    def _get_client(self):
        if self._client is None:
            from advisor.llm_client import get_ollama_client
            self._client = get_ollama_client()
        return self._client

    def classify(self, query: str) -> str:
        """
        Return the query_type string for query.

        Returns one of: 'report', 'code_search', 'explanation', 'command', 'general'.
        Falls back to 'general' on any error so the caller degrades gracefully.
        """
        try:
            client = self._get_client()
            raw = client.generate(
                prompt=_CLASSIFY_PROMPT.format(query=query),
                system=_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=10,
            )
            category = raw.strip().upper().split()[0] if raw.strip() else ""
            if category not in _VALID_CATEGORIES:
                logger.debug(f"LLM classifier returned unexpected category '{category}' — defaulting to general")
                return "general"
            result = _CATEGORY_TO_QUERY_TYPE[category]
            logger.info(f"LLM intent classifier: '{category}' → '{result}'")
            return result
        except Exception as exc:
            logger.debug(f"LLM intent classifier failed ({exc}) — defaulting to general")
            return "general"


_classifier: Optional[LLMIntentClassifier] = None


def get_intent_classifier() -> LLMIntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = LLMIntentClassifier()
    return _classifier
