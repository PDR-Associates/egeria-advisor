"""
Egeria Advisor Web UI — FastAPI application.

Endpoints:
  GET  /                  → index.html
  POST /api/query         → run a query, return result dict
  GET  /api/reports       → report spec catalog grouped by topic
  GET  /api/status        → system / MCP connection status
  POST /api/feedback      → record 👍 / 👎 on a response
"""
from __future__ import annotations

import asyncio
import json
import re
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

_STATIC = Path(__file__).parent / "static"
_SPEC_FILES = [
    Path(__file__).parent.parent.parent / "config" / "report_specs" / "plain_spec_question_specs_batch1.json",
    Path(__file__).parent.parent.parent / "config" / "report_specs" / "report_specs_annotated.json",
]

app = FastAPI(title="Egeria Advisor", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=_STATIC), name="static")

# ── lazy RAG system ────────────────────────────────────────────────────────────

_rag = None


def _get_rag():
    global _rag
    if _rag is None:
        from advisor.rag_system import get_rag_system
        _rag = get_rag_system()
    return _rag


@app.on_event("startup")
async def _startup():
    """Pre-warm the MCP agent in the background so the first report click is fast."""
    import asyncio
    import threading

    def _warm():
        try:
            from advisor.report_pipeline import get_report_pipeline
            get_report_pipeline()._ensure_agent()
            logger.info("MCP agent pre-warmed on startup")
        except Exception as exc:
            logger.warning(f"MCP pre-warm failed (reports will initialize on first use): {exc}")

    threading.Thread(target=_warm, daemon=True).start()


# ── request / response models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    output_format: Optional[str] = None    # reserved; format is detected from query text
    intent_override: Optional[str] = None  # "explanation" | "code_search" | "report" | "command" | "debugging"
    search_string: Optional[str] = None    # filter string for report queries (default "*")
    perspective: Optional[str] = None      # user role: "developer" | "data_engineer" | "data_steward" | "governance_officer"
    page_size: Optional[int] = None        # max graph nodes per report query (None → advisor.yaml default)


class FeedbackRequest(BaseModel):
    query: str
    query_type: str
    vote: int   # 1 = positive, -1 = negative


# ── intent → badge metadata ────────────────────────────────────────────────────

_INTENT_META: Dict[str, Dict[str, str]] = {
    "report":       {"label": "Report",      "color": "#f97316"},
    "command":      {"label": "Act",         "color": "#a855f7"},
    "explanation":  {"label": "Explain",     "color": "#3b82f6"},
    "comparison":   {"label": "Explain",     "color": "#3b82f6"},
    "best_practice":{"label": "Explain",     "color": "#3b82f6"},
    "code_search":  {"label": "Show me",     "color": "#10b981"},
    "example":      {"label": "Show me",     "color": "#10b981"},
    "relationship": {"label": "Reference",   "color": "#14b8a6"},
    "debugging":    {"label": "Troubleshoot","color": "#eab308"},
    "quantitative": {"label": "Reference",   "color": "#14b8a6"},
    "clarification":{"label": "Clarify",     "color": "#f59e0b"},
    "plan":         {"label": "Plan",        "color": "#8b5cf6"},
    "plan_executed":{"label": "Executed",    "color": "#22c55e"},
    "general":      {"label": "Explain",     "color": "#3b82f6"},
}


def _intent_meta(query_type: str) -> Dict[str, str]:
    return _INTENT_META.get(query_type, {"label": query_type.title(), "color": "#64748b"})


# ── report catalog helpers ─────────────────────────────────────────────────────

_TOPIC_PATTERNS: List[tuple] = [
    (re.compile(r"glossar", re.I),           "Glossary"),
    (re.compile(r"collection|folder|namespace|results.set", re.I), "Collections"),
    (re.compile(r"governance.zone|governance.basics|governance.def|governance.polic|governance.control|governance.process", re.I), "Governance"),
    (re.compile(r"data.dict|data.spec|data.struct|data.field|data.class|data.grain|data.value|data.lens", re.I), "Data Structures"),
    (re.compile(r"digital.product|digital.subscript|digital.catalog", re.I), "Digital Products"),
    (re.compile(r"agreement|license|terms.and|regulation|certification", re.I), "Agreements & Compliance"),
    (re.compile(r"project|campaign|task", re.I),  "Projects"),
    (re.compile(r"actor|org.chart|user|team|my.user", re.I), "People & Organisations"),
    (re.compile(r"asset|tech.type|catalog.target", re.I), "Assets"),
    (re.compile(r"solution|information.supply|blueprint", re.I), "Solution Architecture"),
    (re.compile(r"external|related.media|cited", re.I), "External References"),
    (re.compile(r"comment|tag|rating|like", re.I), "Collaboration"),
    (re.compile(r"security|threat|access.control", re.I), "Security"),
]

_DEFAULT_TOPIC = "General"


def _topic_for(name: str) -> str:
    for pat, topic in _TOPIC_PATTERNS:
        if pat.search(name):
            return topic
    return _DEFAULT_TOPIC


def _is_dre(name: str) -> bool:
    return "-dre-" in name.lower()


def _load_report_catalog(include_dre: bool = False) -> Dict[str, List[str]]:
    """Return {topic: [spec_name, ...]} from spec JSON files."""
    catalog: Dict[str, List[str]] = {}
    seen: set = set()
    for path in _SPEC_FILES:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            for name in data:
                if name in seen:
                    continue
                seen.add(name)
                if not include_dre and _is_dre(name):
                    continue
                topic = _topic_for(name)
                catalog.setdefault(topic, []).append(name)
        except Exception as exc:
            logger.warning(f"Failed to load {path}: {exc}")
    # Sort within each topic
    for topic in catalog:
        catalog[topic].sort()
    return dict(sorted(catalog.items()))


# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/query")
async def query_endpoint(req: QueryRequest) -> Dict[str, Any]:
    """Process a natural-language query and return the response dict."""
    user_query = req.query.strip()
    # Append search filter tag so the report pipeline can extract it
    if req.search_string and req.search_string.strip() not in ("", "*"):
        user_query += f" filter:'{req.search_string.strip()}'"

    try:
        rag = _get_rag()
        # Run the blocking RAG query in a thread-pool executor so FastAPI's
        # event loop is not blocked during MCP / LLM calls.  Inside the
        # executor thread, asyncio.get_event_loop().is_running() is False, so
        # _run_async() inside the pipeline uses asyncio.run() directly —
        # cleaner than the nested-thread approach used when called on-loop.
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                rag.query,
                user_query=user_query,
                include_context=True,
                track_metrics=True,
                query_type_override=req.intent_override or None,
                perspective=req.perspective or None,
                page_size=req.page_size or None,
            ),
        )
    except Exception as exc:
        logger.error(f"Query failed: {exc}")
        result = {
            "query": req.query,
            "response": f"Sorry, an error occurred: {exc}",
            "query_type": "general",
            "sources": [],
            "num_sources": 0,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 0.0,
            "context_length": 0,
        }

    query_type = result.get("query_type", "general")
    result["intent"] = _intent_meta(query_type)
    return result


@app.get("/api/reports")
async def list_reports(include_dre: bool = False) -> Dict[str, Any]:
    """Return the report spec catalog grouped by topic."""
    catalog = _load_report_catalog(include_dre=include_dre)
    total = sum(len(v) for v in catalog.values())
    return {"catalog": catalog, "total": total, "include_dre": include_dre}


@app.get("/api/status")
async def system_status() -> Dict[str, Any]:
    """Return connection status for Egeria MCP servers."""
    mcp_status: List[Dict[str, Any]] = []
    try:
        cfg_path = Path(__file__).parent.parent.parent / "config" / "mcp_servers.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            for name, srv in cfg.get("mcpServers", {}).items():
                if name.startswith("_"):
                    continue
                mcp_status.append({
                    "name": name,
                    "enabled": srv.get("enabled", True),
                    "transport": srv.get("transport", "stdio"),
                    "description": srv.get("description", ""),
                })
    except Exception as exc:
        logger.warning(f"Status check failed: {exc}")

    return {"mcp_servers": mcp_status, "rag": "ok"}


@app.get("/api/plans")
async def list_plans() -> Dict[str, Any]:
    """Return inbox and outbox plan document lists."""
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    return {"inbox": dm.list_inbox(), "outbox": dm.list_outbox()}


@app.get("/api/plans/{doc_id}")
async def get_plan(doc_id: str) -> Dict[str, Any]:
    """Return the content of a plan document by doc_id."""
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    content = dm.load(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    folder = "inbox" if (dm.inbox_path() / f"{doc_id}.md").exists() else "outbox"
    return {"doc_id": doc_id, "content": content, "folder": folder}


@app.post("/api/feedback")
async def record_feedback(req: FeedbackRequest) -> Dict[str, str]:
    """Record 👍/👎 feedback."""
    try:
        from advisor.feedback_collector import get_feedback_collector
        fc = get_feedback_collector()
        rating = "positive" if req.vote > 0 else "negative"
        fc.record_feedback(
            query=req.query,
            query_type=req.query_type,
            collections_searched=[],
            response_length=0,
            rating=rating,
        )
    except Exception as exc:
        logger.warning(f"Feedback recording failed: {exc}")
    return {"status": "ok"}
