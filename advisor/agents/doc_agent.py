"""Doc agent — answers conceptual, explanatory, and debugging questions about Egeria."""
from __future__ import annotations

from loguru import logger

from advisor.agents.base import BaseAdvisorAgent

_DOC_COLLECTIONS = ["egeria_concepts", "egeria_general", "egeria_types", "pyegeria"]
_DEBUG_COLLECTIONS = ["egeria_general", "pyegeria", "egeria_concepts"]


class DocAgent(BaseAdvisorAgent):
    def system_prompt(self) -> str:
        return (
            "You are an expert Egeria platform advisor. You explain Egeria concepts, architecture, "
            "governance patterns, and metadata management to technical users and product managers.\n\n"
            "Workflow:\n"
            "1. Call search_egeria_content with the user's question and collections "
            "'egeria_concepts,egeria_general,egeria_types' to find documentation.\n"
            "   - egeria_concepts: short concept definitions (governance zone, glossary, etc.)\n"
            "   - egeria_general: tutorials, guides, and how-tos\n"
            "   - egeria_types: Egeria type system schemas and definitions\n"
            "2. If a Python API is relevant, also search 'pyegeria' to find method signatures.\n"
            "3. Synthesise a clear, accurate answer based ONLY on the retrieved content.\n\n"
            "Rules:\n"
            "- Ground every claim in retrieved content. If you cannot find the answer, say "
            "  'I don't have enough information about that in my indexed documentation.'\n"
            "- For governance/architecture concepts, explain the purpose and design intent, "
            "  not just the technical details.\n"
            "- When a pyegeria API is relevant, show a brief code snippet.\n"
            "- Keep answers concise: lead with the direct answer, then provide detail.\n"
        )

    def tools(self) -> list:
        from advisor.agents.tools import search_egeria_content, get_egeria_symbol
        return [search_egeria_content, get_egeria_symbol]

    def handle(self, query: str, mode: str = "explanation") -> dict:
        collections_hint = (
            "'egeria_concepts,egeria_general,egeria_types,pyegeria'"
            if mode != "debugging"
            else "'egeria_general,pyegeria,egeria_concepts'"
        )
        prompt = (
            f"Question: {query}\n\n"
            f"Start by searching {collections_hint} to find documentation. "
            "Answer based only on what you find."
        )
        try:
            response = self._run_agent(prompt)
            logger.info("DocAgent: BeeAI returned response")
            return _make_result(query, response, mode)
        except Exception as exc:
            logger.warning(f"DocAgent BeeAI run failed: {exc}")

        # Fallback: direct RAG retrieval
        logger.info("DocAgent: falling back to direct retrieval")
        cols = _DEBUG_COLLECTIONS if mode == "debugging" else _DOC_COLLECTIONS
        return _make_result(query, self._fallback(query, cols), mode)

    def _fallback(self, query: str, collections: list[str]) -> str:
        from advisor.agents.tools import _search_egeria_content_raw
        from advisor.llm_client import get_ollama_client

        context = _search_egeria_content_raw(query, collections, top_k=8)
        if not context or context == "No relevant content found.":
            return (
                "I don't have enough information about that in my indexed documentation. "
                "Try asking about a specific Egeria concept, class, or governance pattern."
            )
        if len(context) > 5000:
            context = context[:5000] + "\n...[truncated]"

        system = (
            "You are an expert Egeria platform advisor. Answer the question based ONLY on the "
            "retrieved context. If the context does not contain the answer, say so explicitly — "
            "do not invent information."
        )
        prompt = (
            f"Context:\n{context}\n\n"
            f"Question: {query}\n\n"
            "Answer based only on the context above. Be clear and concise."
        )
        try:
            return get_ollama_client().generate(prompt, system=system, max_tokens=1200)
        except Exception as exc:
            return f"Unable to generate a response: {exc}"


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


_agent: DocAgent | None = None


def get_doc_agent() -> DocAgent:
    global _agent
    if _agent is None:
        _agent = DocAgent()
    return _agent
