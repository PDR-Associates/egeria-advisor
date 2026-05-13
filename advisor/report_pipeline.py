"""
Report pipeline for Egeria Advisor.

Handles QueryType.REPORT queries by:
1. Semantic search over question_spec entries (local, no MCP required)
2. Calling pyegeria MCP find_report_specs as a secondary strategy
3. Selecting the best matching spec
4. Calling run_report with extracted parameters
5. Returning formatted output
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

import numpy as np


def _run_async(coro, timeout: int = 90) -> Any:
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

            t = threading.Thread(target=thread_target, daemon=True)
            t.start()
            t.join(timeout=timeout)
            if t.is_alive():
                raise TimeoutError(f"MCP operation timed out after {timeout}s")
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


def _get_qs_field(item: Any, field: str) -> list:
    """Extract a field from a QuestionSpec object or a plain dict."""
    if isinstance(item, dict):
        return item.get(field, []) or []
    return getattr(item, field, []) or []


class QuestionSpecIndex:
    """
    Lazy in-memory semantic index over all question_spec entries in base_report_specs.

    Uses sentence-transformers for embedding and numpy cosine similarity for search.
    No Milvus or external vector store required — the corpus is small enough (~1000
    questions) that in-memory matrix multiply is fast.

    Thread-safe: build is protected by a lock; after first build the object is read-only.
    """

    _EMBED_MODEL = "all-MiniLM-L6-v2"
    _DEFAULT_THRESHOLD = 0.35
    _DEFAULT_TOP_K = 5

    # Paths relative to the egeria-advisor project root
    _JSON_SOURCES = [
        "config/report_specs/report_specs_annotated.json",
        "config/report_specs/plain_spec_question_specs_batch1.json",
    ]

    def __init__(self, project_root: Optional[str] = None) -> None:
        self._embeddings: Optional[np.ndarray] = None  # (N, D) float32, L2-normalised
        self._entries: List[tuple] = []                # (spec_name, perspectives, question)
        self._model = None
        self._lock = threading.Lock()
        # Resolve project root: caller-supplied → .env lookup → parent of advisor package
        if project_root:
            self._root = project_root
        else:
            import os
            self._root = os.environ.get(
                "EGERIA_ADVISOR_ROOT",
                str(Path(__file__).parent.parent),
            )

    def _load_json_sources(self) -> Dict[str, Any]:
        """Load and merge spec entries from all JSON source files."""
        import json as _json
        merged: Dict[str, Any] = {}
        for rel_path in self._JSON_SOURCES:
            full_path = Path(self._root) / rel_path
            if not full_path.exists():
                logger.debug(f"QuestionSpecIndex: {full_path} not found, skipping.")
                continue
            try:
                with open(full_path) as f:
                    data = _json.load(f)
                for spec_name, entry in data.items():
                    if spec_name not in merged and entry.get("question_spec"):
                        merged[spec_name] = entry
            except Exception as exc:
                logger.warning(f"QuestionSpecIndex: failed to load {full_path}: {exc}")
        return merged

    def _build(self) -> None:
        """Build the index from JSON source files. Called once under lock."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            logger.warning(f"QuestionSpecIndex: sentence-transformers not available — {exc}. Semantic search disabled.")
            return

        spec_data = self._load_json_sources()
        if not spec_data:
            logger.warning("QuestionSpecIndex: no question_spec source files found. Semantic search disabled.")
            return

        model = SentenceTransformer(self._EMBED_MODEL)

        texts: List[str] = []
        entries: List[tuple] = []
        for spec_name, entry in spec_data.items():
            for item in entry.get("question_spec", []):
                perspectives = item.get("perspectives", []) or []
                questions = item.get("questions", []) or []
                for q in questions:
                    if q:
                        entries.append((spec_name, perspectives, q))
                        texts.append(q)

        if not texts:
            logger.warning("QuestionSpecIndex: question_spec entries found but no questions — index is empty.")
            return

        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        self._model = model
        self._entries = entries
        self._embeddings = np.array(embeddings, dtype=np.float32)
        logger.info(
            f"QuestionSpecIndex: built index with {len(texts)} questions "
            f"from {len(spec_data)} specs across {len(self._JSON_SOURCES)} source files."
        )

    def _ensure_built(self) -> None:
        if self._embeddings is not None:
            return
        with self._lock:
            if self._embeddings is not None:
                return
            self._build()

    def search(
        self,
        query: str,
        *,
        top_k: int = _DEFAULT_TOP_K,
        perspective: Optional[str] = None,
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        """
        Find the best-matching report specs for *query*.

        Returns a list of dicts with keys: report_spec, score, perspectives, questions.
        Ordered by descending score; at most *top_k* unique specs returned.
        Returns [] if nothing exceeds *threshold*.
        """
        self._ensure_built()
        if self._embeddings is None or not self._entries:
            return []

        query_vec = self._model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        scores: np.ndarray = self._embeddings @ query_vec  # cosine similarity, shape (N,)

        # If perspective given, zero out entries whose perspectives don't include it
        if perspective:
            persp_lower = perspective.strip().lower()
            for i, (_, persp_list, _) in enumerate(self._entries):
                normed = [p.strip().lower() for p in persp_list]
                if persp_lower not in normed and "any" not in normed:
                    scores[i] = 0.0

        # Collect best score per unique spec name
        best_per_spec: Dict[str, float] = {}
        for idx in range(len(self._entries)):
            s = float(scores[idx])
            if s < threshold:
                continue
            spec_name = self._entries[idx][0]
            if s > best_per_spec.get(spec_name, -1.0):
                best_per_spec[spec_name] = s

        if not best_per_spec:
            return []

        ranked = sorted(best_per_spec.items(), key=lambda kv: -kv[1])[:top_k]
        return [
            {"report_spec": name, "score": score, "perspectives": [], "questions": []}
            for name, score in ranked
        ]


# Module-level singleton — shared across all ReportPipeline instances.
_question_index = QuestionSpecIndex()


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
        """Connect to MCP servers if not already done. Raises ConnectionError if unreachable."""
        if self._agent is not None and self._agent._initialized:
            return

        from advisor.mcp_agent import initialize_mcp_agent
        try:
            # 30s: MCP init spawns two Python subprocesses and connects to Egeria,
            # which takes ~5–15s on first call.  8s was too tight for cold starts.
            self._agent = _run_async(
                initialize_mcp_agent(config_path=self._config_path), timeout=30
            )
        except (TimeoutError, Exception) as exc:
            self._agent = None
            raise ConnectionError(f"Egeria MCP server not reachable: {exc}") from exc

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
        1. Semantic search over question_spec entries (local, no MCP, handles paraphrases)
        2. MCP find_report_specs with extracted keywords (confirms spec exists in live server)
        3. Keyword matching against report names (last resort)

        Returns a list of spec dicts with at least a 'report_spec' or 'name' key.
        """
        # Strategy 1: semantic similarity over question_spec entries
        try:
            semantic_hits = _question_index.search(query, perspective=perspective)
            if semantic_hits:
                logger.debug(
                    f"Semantic search found {len(semantic_hits)} specs: "
                    + ", ".join(f"{h['report_spec']}({h['score']:.2f})" for h in semantic_hits)
                )
                return semantic_hits
        except Exception as exc:
            logger.warning(f"Semantic search failed: {exc}")

        # Strategy 2: MCP question-based search with extracted keywords
        stop = {"show", "me", "the", "a", "an", "list", "all", "get", "run",
                "report", "reports", "for", "of", "in", "on", "about", "what",
                "how", "many", "is", "are", "do", "we", "have", "our", "can",
                "i", "see", "find", "give", "tell", "display", "view"}

        keywords = [w.strip("?.,!") for w in query.lower().split()
                    if w.strip("?.,!") not in stop and len(w.strip("?.,!")) > 2]

        search_terms = []
        if keywords:
            search_terms.append(" ".join(keywords))
            search_terms.extend(keywords)

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

        # Strategy 3: keyword matching against report names
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
        output_type: str = "DICT",
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
                # pyegeria wraps DICT output as {"kind": "json", "data": ...}
                if "kind" in raw and "data" in raw:
                    val = raw["data"]
                    return val if isinstance(val, str) else json.dumps(val, indent=2)
                for key in ("output", "result", "content", "report", "text"):
                    if key in raw:
                        val = raw[key]
                        return val if isinstance(val, str) else json.dumps(val, indent=2)
                return json.dumps(raw, indent=2)
            return str(raw)
        except ConnectionError:
            raise
        except Exception as e:
            logger.warning(f"run_report({report_name}) failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Output formatting helpers
    # ------------------------------------------------------------------

    _FORMAT_KEYWORDS: Dict[str, str] = {
        # User asks for table/structured output → DICT + table render
        "as a table": "TABLE",
        "in a table": "TABLE",
        "as table": "TABLE",
        "tabular": "TABLE",
        "structured": "TABLE",
        # User asks for full report narrative
        "full report": "MARKDOWN",
        "as a report": "MARKDOWN",
        "as report": "MARKDOWN",
        "as markdown": "MARKDOWN",
        "in markdown": "MARKDOWN",
        # Raw JSON
        "as json": "JSON",
        "in json": "JSON",
        "as raw": "JSON",
        # Mermaid diagram
        "as a diagram": "MERMAID",
        "as diagram": "MERMAID",
        "mermaid": "MERMAID",
    }

    def _detect_output_format(self, query: str) -> str:
        """
        Detect user-specified output format from query text.
        Returns "DICT" (default), "MARKDOWN", "JSON", "TABLE", or "MERMAID".
        """
        q = query.lower()
        for phrase, fmt in self._FORMAT_KEYWORDS.items():
            if phrase in q:
                return fmt
        return "DICT"

    @staticmethod
    def _format_output(raw: Any, fmt: str, report_name: str) -> str:
        """
        Convert raw report output (dict / list / str) to the requested display format.
        """
        # run_report() always stringifies its result — try to recover the structure
        if isinstance(raw, str) and fmt in ("TABLE", "DICT"):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                # Not JSON — already a rendered narrative (markdown report)
                return raw

        if isinstance(raw, str):
            return raw  # MARKDOWN / MERMAID already rendered by pyegeria

        if fmt == "JSON":
            return f"```json\n{json.dumps(raw, indent=2)}\n```"

        if fmt == "MERMAID":
            return json.dumps(raw, indent=2)

        # TABLE or DICT — render as markdown table
        return ReportPipeline._dict_to_markdown_table(raw, report_name)

    @staticmethod
    def _dict_to_markdown_table(data: Any, title: str = "") -> str:
        """Render a dict or list of dicts as a markdown table."""
        if not data:
            return f"*No results returned for {title}.*"

        rows: List[Dict[str, Any]] = []
        if isinstance(data, list):
            rows = [r if isinstance(r, dict) else {"Value": r} for r in data]
        elif isinstance(data, dict):
            # Could be {name: {props...}}, {name: [records...]}, or a flat {key: value} record
            sample_val = next(iter(data.values()), None)
            if isinstance(sample_val, dict):
                rows = [{"Name": k, **v} for k, v in data.items()]
            elif isinstance(sample_val, list):
                # Top-level key wraps a list of records — unwrap it
                inner: List[Dict[str, Any]] = []
                for v in data.values():
                    if isinstance(v, list):
                        inner.extend(r if isinstance(r, dict) else {"Value": str(r)} for r in v)
                rows = inner if inner else [{"Property": k, "Value": str(v)} for k, v in data.items()]
            else:
                rows = [{"Property": k, "Value": v} for k, v in data.items()]

        if not rows:
            return json.dumps(data, indent=2)

        # Collect all column names preserving insertion order
        cols: List[str] = []
        for row in rows:
            for k in row:
                if k not in cols:
                    cols.append(k)

        # Cap columns so the table stays readable (drop GUIDs / raw JSON blobs)
        _skip = {"guid", "qualifiedName", "versions", "additionalProperties", "extendedProperties"}
        display_cols = [c for c in cols if c.lower() not in _skip][:8] or cols[:8]

        header = "| " + " | ".join(display_cols) + " |"
        sep = "| " + " | ".join("---" for _ in display_cols) + " |"
        lines = [header, sep]
        for row in rows[:50]:  # safety cap
            cells = [str(row.get(c, "")).replace("|", "\\|")[:80] for c in display_cols]
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    def _try_listing_tool(self, report_name: str) -> Optional[str]:
        """
        When run_report fails for a listing-style spec, try convenience MCP tools
        (egeria_list_glossaries, egeria_list_collections) from the dr-egeria server.
        Returns the output string or None.
        """
        name_lower = report_name.lower()
        tool = None
        if "glossar" in name_lower:
            tool = "egeria_list_glossaries"
        elif "collection" in name_lower:
            tool = "egeria_list_collections"

        if tool is None:
            return None

        try:
            raw = self._call_tool(tool, {})
            if raw is None:
                return None
            return raw if isinstance(raw, str) else str(raw)
        except Exception as exc:
            logger.debug(f"_try_listing_tool({tool}) failed: {exc}")
            return None

    # DrE specs are designed for Dr.Egeria operators and contain operator-facing
    # fields (Journal, Term, Search Keywords) irrelevant to general users.
    # Subtract this from their score so plain pyegeria specs win when available.
    # 0.30 is needed because DrE question_spec questions are very literal and
    # score 0.90+ on common user queries like "show me glossaries".
    _DRE_SCORE_PENALTY = 0.30

    # If the top two candidates are within this margin after re-ranking, ask.
    _DISAMBIG_GAP = 0.12

    # Score above which we run the top spec without asking (overwhelming match).
    _AUTO_RUN_SCORE = 0.85

    @staticmethod
    def _is_dre_spec(name: str) -> bool:
        return "-dre-" in name.lower()

    def _rank_specs(self, specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Re-rank specs: apply a score penalty to DrE specs so that plain pyegeria
        specs are preferred when both match the query equally well.
        """
        ranked = []
        for s in specs:
            name = s.get("report_spec") or s.get("name") or ""
            score = float(s.get("score", 0.0))
            if self._is_dre_spec(name):
                score = max(0.0, score - self._DRE_SCORE_PENALTY)
            ranked.append({**s, "score": score})
        ranked.sort(key=lambda x: -x["score"])
        return ranked

    def _disambiguate(self, query: str, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a clarification response listing the top matching report specs."""
        lines = [
            "I found several reports that could match your query. "
            "Which would you like to run?\n"
        ]
        for i, c in enumerate(candidates, 1):
            name = c.get("report_spec") or c.get("name") or ""
            score = c.get("score", 0.0)
            tag = " *(Dr.Egeria operator view)*" if self._is_dre_spec(name) else ""
            lines.append(f"{i}. **{name}**{tag} — confidence {score:.0%}")
        lines.append(
            "\nReply with the number or the report name, "
            "or say **\"run report [name]\"** directly."
        )
        return {
            "query": query,
            "response": "\n".join(lines),
            "query_type": "clarification",
            "candidates": [c.get("report_spec") or c.get("name") for c in candidates],
            "sources": [],
            "num_sources": 0,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": candidates[0].get("score", 0.0) if candidates else 0.0,
            "context_length": 0,
        }

    # Matches "run report <name>" so a direct selection skips find_specs entirely.
    _RUN_REPORT_RE = re.compile(r"run\s+report\s+(.+)", re.IGNORECASE)
    # Extracts an optional search filter appended by the web UI: filter:'<value>'
    _FILTER_TAG_RE = re.compile(r"\s+filter:'([^']*)'", re.IGNORECASE)

    def _resolve_report_name(self, name: str) -> str:
        """
        Resolve a fuzzy or camelCase report name to the exact spec catalog name.

        Normalises both the input and every known spec name by stripping spaces,
        hyphens, underscores and lowercasing before comparing, so
        "IntegrationConnectors" resolves to "Integration Connectors" etc.
        Returns the original name unchanged if no match is found.
        """
        def _norm(s: str) -> str:
            return re.sub(r"[-_\s]", "", s).lower()

        name_norm = _norm(name)
        try:
            spec_data = _question_index._load_json_sources()
            for spec_name in spec_data:
                if _norm(spec_name) == name_norm:
                    return spec_name
        except Exception as exc:
            logger.debug(f"_resolve_report_name lookup failed: {exc}")
        return name

    def _parse_report_directive(self, raw: str) -> tuple:
        """
        From the captured group of _RUN_REPORT_RE, extract:
          (report_name, search_string)
        Strips any filter tag and any trailing format keywords.
        """
        # Extract search filter if present
        fm = self._FILTER_TAG_RE.search(raw)
        if fm:
            search_string = fm.group(1).strip() or "*"
            raw = raw[:fm.start()].strip()
        else:
            search_string = "*"

        # Strip format keywords that the web UI may have appended
        for phrase in sorted(self._FORMAT_KEYWORDS, key=len, reverse=True):
            if raw.lower().endswith(phrase):
                raw = raw[:-len(phrase)].strip()
                break

        return raw, search_string

    def process(self, query: str, perspective: Optional[str] = None) -> Dict[str, Any]:
        """
        Full report pipeline: discover spec → run report → return response dict.

        Falls back to a helpful message if no spec is found or Egeria is unreachable.
        """
        # Direct dispatch: "run report <name>" bypasses find_specs / disambiguation.
        m = self._RUN_REPORT_RE.match(query.strip())
        if m:
            report_name, search_string = self._parse_report_directive(m.group(1).strip())
            # Normalise camelCase / variant spellings to the exact catalog name
            report_name = self._resolve_report_name(report_name)
            logger.info(f"Direct report dispatch: {report_name!r} search={search_string!r}")
            return self._execute_report(query, report_name, search_string=search_string)

        try:
            specs = self.find_specs(query, perspective=perspective)
        except Exception as e:
            logger.error(f"ReportPipeline.find_specs raised: {e}")
            return _no_report_found(query)

        if not specs:
            logger.info("No matching report specs found for query")
            return _no_report_found(query)

        ranked = self._rank_specs(specs)
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None

        top_score = top.get("score", 0.0)
        second_score = second.get("score", 0.0) if second else 0.0

        # When two specs are equally plausible and score is not overwhelming, ask.
        if (second is not None
                and top_score < self._AUTO_RUN_SCORE
                and (top_score - second_score) < self._DISAMBIG_GAP):
            logger.info(
                f"Disambiguation: top={top.get('report_spec')} ({top_score:.2f}), "
                f"second={second.get('report_spec')} ({second_score:.2f})"
            )
            return self._disambiguate(query, ranked[:3])

        best = top
        report_name = (
            best.get("report_spec") or best.get("name") or
            best.get("spec_name") or best.get("report_name") or ""
        )
        if not report_name:
            logger.warning("Spec has no usable name field")
            return _no_report_found(query)

        return self._execute_report(query, report_name, num_specs_found=len(ranked))

    def _execute_report(
        self, query: str, report_name: str, num_specs_found: int = 1,
        search_string: str = "*",
    ) -> Dict[str, Any]:
        """Shared execution path: run a named report and format the result."""
        fmt = self._detect_output_format(query)
        mcp_output_type = "MARKDOWN" if fmt == "MARKDOWN" else ("MERMAID" if fmt == "MERMAID" else "DICT")

        logger.info(
            f"Running report: {report_name} (output_type={mcp_output_type}, "
            f"display_fmt={fmt}, search_string={search_string!r})"
        )
        mcp_connected = False
        connection_err: Optional[str] = None
        raw_output = None
        try:
            self._ensure_agent()
            mcp_connected = True
            raw_output = self.run_report(report_name, search_string=search_string, output_type=mcp_output_type)
        except ConnectionError as exc:
            connection_err = str(exc)

        if raw_output is None and mcp_connected:
            raw_output = self._try_listing_tool(report_name)


        output = self._format_output(raw_output, fmt, report_name) if raw_output is not None else None

        if output is None:
            if not mcp_connected:
                detail = f"\n\n*Connection detail: {connection_err}*" if connection_err else ""
                err_response = (
                    f"I found the **{report_name}** report that matches your query, "
                    "but the Egeria MCP server is not reachable right now.\n\n"
                    f"To run this report via Dr.Egeria: `[[{report_name}]]`\n\n"
                    "Make sure the pyegeria MCP server is running before retrying."
                    + detail +
                    "\n\n*Output format options: append \"as a table\", \"full report\", "
                    "\"as json\", or \"as a diagram\" to your query.*"
                )
            else:
                err_response = (
                    f"The report **{report_name}** could not be executed — it may not exist "
                    "or returned no results for the given search string.\n\n"
                    "Tips:\n"
                    "- Ask me to *list available reports* to browse what's available\n"
                    "- Try clicking a report from the left sidebar for exact name matching\n"
                    f"- To run via Dr.Egeria: `[[{report_name}]]`\n\n"
                    "*Output format options: append \"as a table\", \"full report\", "
                    "\"as json\", or \"as a diagram\" to your query.*"
                )
            return {
                "query": query,
                "response": err_response,
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
            "num_specs_found": num_specs_found,
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
