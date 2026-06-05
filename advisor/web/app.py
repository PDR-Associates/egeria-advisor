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

from advisor.web.admin import router as _admin_router
app.include_router(_admin_router)

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
    draft_id: Optional[str] = None         # active planning session draft ID


class FeedbackRequest(BaseModel):
    query: str
    query_type: str
    vote: int                           # 1 = positive, -1 = negative
    perspective: Optional[str] = None
    routing_agent: Optional[str] = None


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
    "plan":              {"label": "Plan",        "color": "#8b5cf6"},
    "plan_clarification":{"label": "Planning",    "color": "#a78bfa"},
    "plan_executed":     {"label": "Executed",    "color": "#22c55e"},
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
                draft_id=req.draft_id or None,
            ),
        )
    except Exception as exc:
        logger.error(f"Query failed: {exc}")
        result = {
            "query": req.query,
            "response": f"Sorry, an error occurred: {exc}",
            "query_type": "general",
            "routing_agent": "error",
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
    """Return inbox and outbox plan document lists, annotated with active draft IDs."""
    from advisor.governance_docs import get_doc_manager
    from advisor.governance_draft import get_draft_manager
    dm = get_doc_manager()
    inbox = dm.list_inbox()
    outbox = dm.list_outbox()

    # Build doc_id → draft_id map for plans that have an active refine/generate draft
    doc_to_draft: Dict[str, str] = {}
    for d in get_draft_manager().list_drafts():
        if d.get("doc_id") and d.get("phase") in ("generate", "refine", "template_offer"):
            doc_to_draft[d["doc_id"]] = d["draft_id"]

    for entry in inbox:
        entry["draft_id"] = doc_to_draft.get(entry.get("doc_id"))

    return {"inbox": inbox, "outbox": outbox}


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


@app.put("/api/plans/{doc_id}")
async def save_plan(doc_id: str, body: Dict[str, Any]) -> Dict[str, str]:
    """Save updated plan content to inbox (with automatic version backup)."""
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager
    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    dm = get_doc_manager()
    ok = dm.update(doc_id, content)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found in inbox")
    return {"status": "ok"}


@app.post("/api/plans/{doc_id}/validate")
async def validate_plan(doc_id: str) -> Dict[str, Any]:
    """Run Dr.Egeria validate directive on the plan's command section."""
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager
    from advisor.agents.governance_plan_agent import GovernancePlanAgent
    from advisor.agents.dr_egeria_agent import DrEgeriaActionAgent
    dm = get_doc_manager()
    content = dm.load(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    cmd_section = GovernancePlanAgent._extract_command_section(content)
    if not cmd_section.strip():
        return {"status": "ok", "result": "No commands to validate."}
    action_agent = DrEgeriaActionAgent()
    try:
        result = action_agent.execute(cmd_section, directive="validate", dry_run=False)
        return {"status": "ok", "result": result}
    except ConnectionError as exc:
        return {"status": "error", "result": f"MCP server not reachable: {exc}"}
    except Exception as exc:
        return {"status": "error", "result": f"Validation failed: {exc}"}


@app.get("/api/drafts")
async def list_drafts() -> Dict[str, Any]:
    """Return active planning session drafts."""
    from advisor.governance_draft import get_draft_manager
    return {"drafts": get_draft_manager().list_drafts()}


@app.get("/api/drafts/{draft_id}")
async def get_draft(draft_id: str) -> Dict[str, Any]:
    """Return a single draft spec by ID (for the Plan Canvas)."""
    from fastapi import HTTPException
    from advisor.governance_draft import get_draft_manager
    spec = get_draft_manager().load(draft_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id!r} not found")
    return spec


@app.patch("/api/drafts/{draft_id}/commands")
async def patch_draft_commands(draft_id: str, body: Dict[str, Any]) -> Dict[str, str]:
    """Update commands and answers in a draft (called by Plan Canvas on reorder/add/remove/edit)."""
    from fastapi import HTTPException
    from advisor.governance_draft import get_draft_manager
    dm = get_draft_manager()
    spec = dm.load(draft_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id!r} not found")
    if "commands" in body:
        spec["commands_identified"] = body["commands"]
    if "answers" in body:
        spec["answers"] = body["answers"]
    dm.save(spec)
    return {"status": "ok"}


@app.delete("/api/drafts/{draft_id}")
async def delete_draft(draft_id: str) -> Dict[str, str]:
    """Discard a planning session draft."""
    from advisor.governance_draft import get_draft_manager
    deleted = get_draft_manager().delete(draft_id)
    return {"status": "ok" if deleted else "not_found"}


@app.get("/api/plan-templates")
async def list_plan_templates() -> Dict[str, Any]:
    """Return available plan templates."""
    from advisor.plan_templates import get_template_manager
    return {"templates": get_template_manager().list_templates()}


@app.delete("/api/plan-templates/{name}")
async def delete_plan_template(name: str) -> Dict[str, str]:
    """Delete a plan template by name."""
    from urllib.parse import unquote
    from advisor.plan_templates import get_template_manager
    deleted = get_template_manager().delete(unquote(name))
    return {"status": "ok" if deleted else "not_found"}


@app.get("/api/templates/{command_name}/fields")
async def get_template_fields(command_name: str, level: str = "basic") -> Dict[str, Any]:
    """Return template field metadata for a Dr.Egeria command at the given template level."""
    from urllib.parse import unquote
    from advisor.agents.tools import _templates_root, _normalise
    from advisor.agents.dr_egeria_agent import parse_template

    action = unquote(command_name)
    root   = _templates_root()
    if root is None:
        return {"fields": [], "level": level}

    level_dir = root / level
    if not level_dir.is_dir():
        level_dir = root / "basic"

    query_norm = _normalise(action)
    words      = [_normalise(w) for w in action.split() if len(w) > 3]

    best_score = 0
    best_file  = None
    for md_file in sorted(level_dir.rglob("*.md")):
        stem_norm = _normalise(md_file.stem)
        score = 0
        if query_norm == stem_norm:           score = 50
        elif query_norm in stem_norm:         score = 40
        elif stem_norm in query_norm:         score = 35
        elif words:
            hits = sum(1 for w in words if w in stem_norm)
            if hits == len(words):            score = 30
            elif hits > 0:                    score = 20 + hits
        if score > best_score:
            best_score = score
            best_file  = md_file

    if best_file is None or best_score == 0:
        return {"fields": [], "level": level}

    try:
        template = parse_template(str(best_file))
    except Exception:
        return {"fields": [], "level": level}

    return {
        "level": level,
        "fields": [
            {
                "name":               a["name"],
                "required":           a["required"],
                "type":               a["type"],
                "description":        a.get("description", ""),
                "valid_values":       a.get("valid_values", []),
                "default_value":      a.get("default_value", ""),
                "alternative_labels": a.get("alternative_labels", []),
            }
            for a in template["attributes"]
        ],
    }


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
            perspective=req.perspective or None,
            routing_agent=req.routing_agent or None,
        )
    except Exception as exc:
        logger.warning(f"Feedback recording failed: {exc}")
    return {"status": "ok"}


@app.get("/api/perspectives")
async def list_perspectives() -> Dict[str, Any]:
    """Return available perspectives (live from Egeria or CSV fallback)."""
    from advisor.perspective_manager import get_all
    return {"perspectives": get_all()}


@app.get("/api/feedback/analysis")
async def feedback_analysis() -> Dict[str, Any]:
    """Return feedback statistics plus gap analysis."""
    from advisor.feedback_collector import get_feedback_collector
    fc = get_feedback_collector()
    return {
        "stats": fc.get_feedback_stats(),
        "gaps": fc.get_gap_analysis(),
        "improvements": fc.get_routing_improvements(),
    }
