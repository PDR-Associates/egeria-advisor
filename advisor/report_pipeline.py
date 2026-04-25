"""
Report pipeline for Egeria Advisor.

Handles QueryType.REPORT queries by:
1. Calling pyegeria MCP find_report_specs to discover relevant specs
2. Selecting the best matching spec
3. Calling run_report with extracted parameters
4. Returning formatted output
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, List, Optional
from loguru import logger


def _run_async(coro) -> Any:
    """Run an async coroutine from sync code safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an event loop (e.g., Jupyter) — use a new thread
            result_container: list = []
            exc_container: list = []

            def thread_target():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    result_container.append(new_loop.run_until_complete(coro))
                except Exception as exc:
                    exc_container.append(exc)
                finally:
                    new_loop.close()

            t = threading.Thread(target=thread_target)
            t.start()
            t.join(timeout=90)
            if exc_container:
                raise exc_container[0]
            return result_container[0] if result_container else None
    except RuntimeError:
        pass

    return asyncio.run(coro)


def _unwrap_mcp_content(raw: Any) -> Any:
    """
    MCP tool results come back as a list of content blocks:
      [{"type": "text", "text": "<json-or-text>"}, ...]
    Extract and parse the text.  If the text is JSON, return the parsed object.
    If the result is an error string, return None so callers can handle gracefully.
    """
    if raw is None:
        return None

    # Already unwrapped (string or dict)
    if isinstance(raw, (dict, str)) and not isinstance(raw, list):
        return _maybe_parse_json(raw)

    if isinstance(raw, list):
        texts = []
        for item in raw:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)

        if not texts:
            return raw  # Unknown structure — return as-is

        combined = "\n".join(texts).strip()

        # Check for error responses from the MCP server
        if combined.startswith("Error ") or "Error executing tool" in combined:
            logger.warning(f"MCP tool returned error: {combined[:200]}")
            return None

        return _maybe_parse_json(combined)

    return raw


def _normalise_spec_list(raw: Any) -> List[Dict[str, Any]]:
    """Normalise whatever find_report_specs returned into a list of spec dicts."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("Matching Report Specs", "specs", "result", "matches", "items"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        if "report_spec" in raw or "name" in raw or "spec_name" in raw:
            return [raw]
    return []


def _deduplicate_specs(specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate entries for the same report_spec name, keeping the first."""
    seen: set = set()
    result = []
    for spec in specs:
        name = spec.get("report_spec") or spec.get("name") or spec.get("spec_name") or ""
        if name and name not in seen:
            seen.add(name)
            result.append(spec)
    return result


def _maybe_parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


class ReportPipeline:
    """
    Pipeline for discovering and executing Egeria reports via MCP.

    The pipeline is lazy — MCP agent is only connected on first use.
    All public methods are synchronous to match the existing RAG dispatch pattern.
    """

    def __init__(self, config_path: str = "config/mcp_servers.json"):
        self._config_path = config_path
        self._agent = None  # lazy

    def _ensure_agent(self):
        """Connect to MCP servers if not already done."""
        if self._agent is not None and self._agent._initialized:
            return

        from advisor.mcp_agent import initialize_mcp_agent
        self._agent = _run_async(initialize_mcp_agent(config_path=self._config_path))

    def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Synchronously call an MCP tool and unwrap MCP content envelope."""
        self._ensure_agent()
        raw = _run_async(self._agent.execute_tool(tool_name, arguments))
        return _unwrap_mcp_content(raw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_specs(self, query: str, perspective: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Find report specs relevant to *query*.

        Strategy:
        1. Try question-based search using extracted keywords (full query, then single keywords)
        2. Fall back to keyword-based name matching from list_reports

        Returns a list of spec dicts with at least a 'report_spec' or 'name' key.
        """
        # Strategy 1: question-based search — try progressively simpler queries
        stop = {"show", "me", "the", "a", "an", "list", "all", "get", "run",
                "report", "reports", "for", "of", "in", "on", "about", "what",
                "how", "many", "is", "are", "do", "we", "have", "our", "can",
                "i", "see", "find", "give", "tell", "display", "view"}

        keywords = [w.strip("?.,!") for w in query.lower().split()
                    if w.strip("?.,!") not in stop and len(w.strip("?.,!")) > 2]

        search_terms = []
        if keywords:
            search_terms.append(" ".join(keywords))  # try keywords combined
            search_terms.extend(keywords)            # then each keyword separately

        for term in search_terms:
            try:
                args: Dict[str, Any] = {"question": term}
                if perspective:
                    args["perspective"] = perspective

                raw = self._call_tool("find_report_specs", args)
                if raw is not None:
                    specs = _normalise_spec_list(raw)
                    if specs:
                        return _deduplicate_specs(specs)
            except Exception as e:
                logger.warning(f"find_report_specs({term!r}) failed: {e}")
                continue

        # Strategy 2: keyword matching against report names
        return self._find_specs_by_keywords(query)

    def _find_specs_by_keywords(self, query: str) -> List[Dict[str, Any]]:
        """
        Fallback: fetch all report names and return those whose name contains
        any keyword from the query.
        """
        try:
            all_specs = self._call_tool("list_reports", {})
            if not isinstance(all_specs, dict):
                return []

            query_lower = query.lower()
            # Extract meaningful keywords (ignore stop words)
            stop = {"show", "me", "the", "a", "an", "list", "all", "get", "run",
                    "report", "reports", "for", "of", "in", "on", "about", "what"}
            keywords = [w.strip("?.,!") for w in query_lower.split()
                        if w.strip("?.,!") not in stop and len(w) > 2]

            if not keywords:
                return []

            matches = []
            for name in all_specs.keys():
                name_lower = name.lower()
                if any(kw in name_lower for kw in keywords):
                    matches.append({"report_spec": name, "perspectives": [], "questions": []})

            return sorted(matches, key=lambda d: d["report_spec"])
        except Exception as e:
            logger.warning(f"Keyword fallback for find_specs failed: {e}")
            return []

    def run_report(
        self,
        report_name: str,
        search_string: str = "*",
        output_type: str = "MARKDOWN",
    ) -> Optional[str]:
        """
        Execute a named report and return the output string.

        Returns None on failure.
        """
        try:
            args = {
                "report_name": report_name,
                "search_string": search_string,
                "output_type": output_type,
            }
            raw = self._call_tool("run_report", args)
            if raw is None:
                return None

            if isinstance(raw, str):
                return raw
            if isinstance(raw, dict):
                for key in ("output", "result", "content", "report", "text"):
                    if key in raw:
                        val = raw[key]
                        return val if isinstance(val, str) else json.dumps(val, indent=2)
                return json.dumps(raw, indent=2)
            return str(raw)
        except Exception as e:
            logger.warning(f"run_report({report_name}) failed: {e}")
            return None

    def process(self, query: str) -> Dict[str, Any]:
        """
        Full report pipeline: discover spec → run report → return response dict.

        Falls back to a helpful message if no spec is found or Egeria is unreachable.
        """
        try:
            specs = self.find_specs(query)
        except Exception as e:
            logger.error(f"ReportPipeline.find_specs raised: {e}")
            return _no_report_found(query)

        if not specs:
            logger.info("No matching report specs found for query")
            return _no_report_found(query)

        # Pick the first (best-ranked) spec
        best = specs[0]
        report_name = (
            best.get("report_spec") or best.get("name") or
            best.get("spec_name") or best.get("report_name") or ""
        )
        if not report_name:
            logger.warning("Spec has no usable name field")
            return _no_report_found(query)

        logger.info(f"Running report: {report_name}")
        output = self.run_report(report_name)

        if output is None:
            return {
                "query": query,
                "response": (
                    f"Found report spec **{report_name}** but could not execute it. "
                    "Egeria may not be running or the report requires additional parameters."
                ),
                "query_type": "report",
                "report_name": report_name,
                "sources": [],
                "num_sources": 0,
                "retrieval_time": 0.0,
                "generation_time": 0.0,
                "avg_relevance_score": 0.0,
                "context_length": 0,
            }

        return {
            "query": query,
            "response": output,
            "query_type": "report",
            "report_name": report_name,
            "num_specs_found": len(specs),
            "sources": [f"pyegeria MCP → {report_name}"],
            "num_sources": 1,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 0.0,
            "context_length": len(output),
        }


def _no_report_found(query: str) -> Dict[str, Any]:
    return {
        "query": query,
        "response": (
            "I couldn't find a matching Egeria report for that query. "
            "You can ask me to *list available reports* to see what's available, "
            "or rephrase your request."
        ),
        "query_type": "report",
        "sources": [],
        "num_sources": 0,
        "retrieval_time": 0.0,
        "generation_time": 0.0,
        "avg_relevance_score": 0.0,
        "context_length": 0,
    }


# Singleton
_report_pipeline: Optional[ReportPipeline] = None


def get_report_pipeline() -> ReportPipeline:
    global _report_pipeline
    if _report_pipeline is None:
        _report_pipeline = ReportPipeline()
    return _report_pipeline
