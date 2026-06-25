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

from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

_STATIC = Path(__file__).parent / "static"
_SPEC_FILES = [
    Path(__file__).parent.parent.parent / "config" / "report_specs" / "plain_spec_question_specs_batch1.json",
    Path(__file__).parent.parent.parent / "config" / "report_specs" / "report_specs_annotated.json",
]

app = FastAPI(title="Egeria Advisor", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://localhost(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
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
    output_format: Optional[str] = None    # "LIST"|"TABLE"|"MERMAID"|"MD"|"JSON"|"DICT" — overrides auto-detect
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
    response_text: Optional[str] = None   # actual response shown to user
    intent_override: Optional[str] = None  # intent selector value from UI ("auto", "explain", etc.)


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


# Canonical, ordered set of browser-renderable output formats. `value` is the
# token sent to pyegeria (via the fmt:'<value>' query tag); `label` is shown in
# the picker. A spec's declared `formats[].types` are intersected with this set
# (and `ALL` expands to all of it) to build a spec-aware dropdown.
_BROWSER_FORMATS: List[tuple] = [
    ("LIST",    "List — compact Markdown table"),
    ("TABLE",   "Table — structured data table"),
    ("REPORT",  "Report — full narrative (Mermaid, graphs)"),
    ("FORM",    "Form — Dr.Egeria editable form"),
    ("MERMAID", "Diagram — Mermaid graph"),
    ("HTML",    "HTML — rendered page"),
    ("MD",      "Markdown — simple"),
    ("DICT",    "Dict — materialized properties"),
    ("JSON",    "JSON — raw Egeria response"),
]
_BROWSER_FORMAT_VALUES = [v for v, _ in _BROWSER_FORMATS]


def _spec_supported_formats(name: str) -> List[str]:
    """Return the browser-renderable output formats a spec supports, in canonical
    order. Reads the in-process pyegeria registry; `ALL` expands to every browser
    format. Falls back to a safe default if the spec/registry is unavailable."""
    try:
        from pyegeria.view.base_report_formats import get_report_registry
        fs = get_report_registry().get(name)
        if fs is None:
            return list(_BROWSER_FORMAT_VALUES)
        declared = {
            t.upper()
            for fmt in (getattr(fs, "formats", []) or [])
            for t in (getattr(fmt, "types", []) or [])
        }
        if "ALL" in declared:
            return list(_BROWSER_FORMAT_VALUES)
        supported = [v for v in _BROWSER_FORMAT_VALUES if v in declared]
        # Always offer at least DICT so the report is runnable from the picker.
        return supported or ["DICT"]
    except Exception as exc:
        logger.debug(f"_spec_supported_formats({name}) failed: {exc}")
        return list(_BROWSER_FORMAT_VALUES)


def _catalog_formats(catalog: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Build {spec_name: [supported formats]} for every spec in the catalog."""
    formats: Dict[str, List[str]] = {}
    for names in catalog.values():
        for name in names:
            formats[name] = _spec_supported_formats(name)
    return formats


def _is_runnable_spec(name: str) -> bool:
    """Return True if the spec has an action (can be executed standalone)."""
    try:
        from pyegeria.view.base_report_formats import get_report_registry
        spec = get_report_registry().get(name)
        if spec is None:
            return True  # unknown to registry — assume runnable, let executor decide
        return getattr(spec, "action", None) is not None
    except Exception:
        return True  # registry unavailable — assume runnable


def _load_report_catalog(include_dre: bool = False) -> Dict[str, List[str]]:
    """Return {topic: [spec_name, ...]} from spec JSON files, runnable specs only."""
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
                if not _is_runnable_spec(name):
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


# ── Auth endpoints ─────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class PortalTokenRequest(BaseModel):
    portal_token: str


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest) -> Dict[str, Any]:
    """Validate Egeria credentials and return a JWT."""
    from advisor.auth import validate_egeria_credentials, create_access_token
    if not req.username or not req.password:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="username and password required")
    ok = await asyncio.get_event_loop().run_in_executor(
        None, validate_egeria_credentials, req.username, req.password
    )
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid credentials or Egeria is unreachable.")
    token = create_access_token(
        user_id=req.username,
        egeria_user=req.username,
        egeria_password=req.password,
    )
    return {"access_token": token, "token_type": "bearer", "egeria_user": req.username}


@app.post("/api/auth/portal")
async def auth_portal(req: PortalTokenRequest) -> Dict[str, Any]:
    """Exchange a Portal-issued short-lived token for a local JWT."""
    from advisor.auth import exchange_portal_token, create_access_token
    payload = exchange_portal_token(req.portal_token)
    egeria_user = payload.get("egeria_user", "")
    egeria_password = payload.get("egeria_password", "")
    if not egeria_user:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Portal token missing egeria_user.")
    token = create_access_token(
        user_id=egeria_user,
        egeria_user=egeria_user,
        egeria_password=egeria_password,
    )
    return {"access_token": token, "token_type": "bearer", "egeria_user": egeria_user}


@app.get("/api/auth/me")
async def auth_me(request: Request) -> Dict[str, Any]:
    """Return info about the currently authenticated user."""
    from advisor.auth import get_current_user
    user = get_current_user(request)
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user_id": user.get("sub", ""),
        "egeria_user": user.get("egeria_user", ""),
    }


@app.post("/api/auth/logout")
async def auth_logout() -> Dict[str, str]:
    """Client-side logout — server has no session state to clear."""
    return {"status": "ok"}


@app.post("/api/query")
async def query_endpoint(request: Request, req: QueryRequest) -> Dict[str, Any]:
    """Process a natural-language query and return the response dict."""
    from advisor.auth import get_current_user
    current_user = get_current_user(request)
    egeria_authenticated = current_user is not None

    user_query = req.query.strip()
    # Append search filter tag so the report pipeline can extract it
    if req.search_string and req.search_string.strip() not in ("", "*"):
        user_query += f" filter:'{req.search_string.strip()}'"
    # Append output format tag when explicitly set (e.g. from the report modal dropdown)
    if req.output_format:
        user_query += f" fmt:'{req.output_format.strip()}'"

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
                egeria_authenticated=egeria_authenticated,
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


@app.post("/api/query/stream")
async def query_stream_endpoint(request: Request, req: QueryRequest) -> StreamingResponse:
    """
    Streaming variant of /api/query — returns Server-Sent Events.

    Event sequence:
      data: {"type":"start","query":"..."}
      data: {"type":"token","text":"..."}   (repeated, only for LLM-generation paths)
      data: {"type":"done","result":{...}}
      data: [DONE]
    """
    from advisor.auth import get_current_user
    current_user = get_current_user(request)
    egeria_authenticated = current_user is not None

    user_query = req.query.strip()
    if req.search_string and req.search_string.strip() not in ("", "*"):
        user_query += f" filter:'{req.search_string.strip()}'"
    if req.output_format:
        user_query += f" fmt:'{req.output_format.strip()}'"

    loop = asyncio.get_event_loop()
    rag  = _get_rag()

    async def event_gen():
        # Bridge sync generator → async generator via asyncio.Queue so the
        # event loop stays unblocked while the worker thread produces tokens.
        q: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=256)

        def producer() -> None:
            try:
                for chunk in rag.query_stream(
                    user_query=user_query,
                    include_context=True,
                    query_type_override=req.intent_override or None,
                    perspective=req.perspective or None,
                    page_size=req.page_size or None,
                    draft_id=req.draft_id or None,
                    egeria_authenticated=egeria_authenticated,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, chunk)
            except Exception as exc:
                logger.error(f"query_stream producer error: {exc}", exc_info=True)
                err = json.dumps({"type": "error", "message": str(exc)})
                loop.call_soon_threadsafe(q.put_nowait, f"data: {err}\n\n")
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)  # sentinel

        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = loop.run_in_executor(executor, producer)

        while True:
            item = await q.get()
            if item is None:
                break
            yield item

        await future
        executor.shutdown(wait=False)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )


@app.get("/api/reports")
async def list_reports(include_dre: bool = False) -> Dict[str, Any]:
    """Return the report spec catalog grouped by topic."""
    catalog = _load_report_catalog(include_dre=include_dre)
    total = sum(len(v) for v in catalog.values())
    formats = _catalog_formats(catalog)
    return {
        "catalog": catalog,
        "formats": formats,
        "format_labels": dict(_BROWSER_FORMATS),
        "total": total,
        "include_dre": include_dre,
    }


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


@app.post("/api/plans/import")
async def import_plan(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Import an externally-written Dr.Egeria/LGCI markdown document as a new
    managed plan in inbox. Detects whether the content is already LGCI-structured
    or a bare Dr.Egeria command file and wraps the latter automatically.
    """
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    title = (body.get("title") or "").strip() or None
    dm = get_doc_manager()
    try:
        doc_id = dm.import_document(content, title=title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", "doc_id": doc_id, "folder": "inbox"}


@app.get("/api/plans")
async def list_plans() -> Dict[str, Any]:
    """Return inbox, outbox, and trash plan document lists, annotated with active draft IDs."""
    from advisor.governance_docs import get_doc_manager
    from advisor.governance_draft import get_draft_manager
    dm = get_doc_manager()
    inbox = dm.list_inbox()
    outbox = dm.list_outbox()
    trash = dm.list_trash()

    # Build doc_id → draft_id map for plans that have an active refine/generate draft
    doc_to_draft: Dict[str, str] = {}
    for d in get_draft_manager().list_drafts():
        if d.get("doc_id") and d.get("phase") in ("generate", "refine", "template_offer"):
            doc_to_draft[d["doc_id"]] = d["draft_id"]

    for entry in inbox:
        entry["draft_id"] = doc_to_draft.get(entry.get("doc_id"))

    return {"inbox": inbox, "outbox": outbox, "trash": trash}


@app.get("/api/plans/{doc_id}")
async def get_plan(doc_id: str) -> Dict[str, Any]:
    """Return the content of a plan document by doc_id (inbox, outbox, or trash)."""
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    content = dm.load(doc_id, include_trash=True)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    folder = dm.folder_of(doc_id) or "outbox"
    return {"doc_id": doc_id, "content": content, "folder": folder}


@app.get("/api/plans/{doc_id}/export")
async def export_plan(doc_id: str) -> Response:
    """Download the full current content of a plan document (inbox or outbox)."""
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    content = dm.load(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.md"'},
    )


@app.get("/api/plans/{doc_id}/report-export")
async def export_plan_report(doc_id: str) -> Response:
    """
    Download just the report content (Mermaid diagrams, result tables) extracted
    from an executed plan's Dr.Egeria output — shareable independent of the plan
    that produced it.
    """
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager, DocumentManager
    from advisor.agents.outcome_reporter import _extract_report_sections

    dm = get_doc_manager()
    content = dm.load_outbox(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found in outbox")

    # The raw Dr.Egeria output lives inside the collapsible "## Dr.Egeria Execution
    # Output" section appended by GovernancePlanAgent.execute() — pull it out.
    m = re.search(
        r'<summary>.*?</summary>\n\n(.*?)\n\n</details>',
        content, re.DOTALL,
    )
    raw_output = m.group(1) if m else content
    report_md = _extract_report_sections(raw_output)
    if not report_md:
        raise HTTPException(
            status_code=404,
            detail="No extractable report content (Mermaid diagram or result table) found in this plan's output",
        )

    title = DocumentManager._extract_title(content)
    final = (
        f"# {title} — Report\n\n"
        f"*Generated from plan `{doc_id}` on {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
        f"{report_md}\n"
    )
    return Response(
        content=final,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}_report.md"'},
    )


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
    from advisor.agents.governance_plan_agent import get_governance_plan_agent
    agent = get_governance_plan_agent()
    result = await asyncio.get_event_loop().run_in_executor(
        None, agent.validate, doc_id
    )
    return result


@app.post("/api/plans/{doc_id}/retry")
async def retry_plan(doc_id: str) -> Dict[str, Any]:
    """Move a failed outbox plan back to inbox and re-execute it immediately."""
    from advisor.agents.governance_plan_agent import get_governance_plan_agent
    agent = get_governance_plan_agent()
    result = await asyncio.get_event_loop().run_in_executor(
        None, agent.retry, doc_id
    )
    return result


@app.post("/api/plans/{doc_id}/rerun")
async def rerun_plan(doc_id: str) -> Dict[str, Any]:
    """
    Re-execute an outbox plan directly, in place — no inbox detour.
    Appends a new "## Outcome (Run N)" section to the same outbox document.
    """
    from advisor.agents.governance_plan_agent import get_governance_plan_agent
    agent = get_governance_plan_agent()
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: agent.execute(doc_id, source_folder="outbox")
    )
    return result


@app.post("/api/plans/{doc_id}/recover")
async def recover_plan(doc_id: str) -> Dict[str, Any]:
    """Move an outbox plan back to inbox for editing (does NOT re-execute)."""
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    moved = dm.move_to_inbox(doc_id)
    if not moved:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=f"Could not recover {doc_id!r} — it may not be in the outbox, or inbox already has a copy.")
    return {"status": "ok", "doc_id": doc_id, "folder": "inbox"}


@app.get("/api/plans/{doc_id}/versions")
async def list_plan_versions(doc_id: str) -> Dict[str, Any]:
    """List available versions for a plan document."""
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    versions = dm.list_versions(doc_id)
    return {"doc_id": doc_id, "versions": versions}


@app.post("/api/plans/{doc_id}/versions/{version_file:path}/restore")
async def restore_plan_version(doc_id: str, version_file: str) -> Dict[str, Any]:
    """Restore a specific version of a plan to inbox."""
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    dm = get_doc_manager()
    ok = dm.restore_version(doc_id, version_file)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Version {version_file!r} not found")
    return {"status": "ok", "doc_id": doc_id, "restored_from": version_file}


@app.post("/api/plans/{doc_id}/fork")
async def fork_plan(doc_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new, independent plan seeded from doc_id (or a specific version
    of it). Known objects (Qualified Name + GUID) from the source's Command
    Results table are carried forward as a reference appendix.
    """
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    version_file = body.get("version_file") or None
    dm = get_doc_manager()
    try:
        new_doc_id = dm.fork(doc_id, title, version_file=version_file)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", "doc_id": new_doc_id, "forked_from": doc_id}


@app.delete("/api/plans/{doc_id}")
async def delete_plan(doc_id: str) -> Dict[str, Any]:
    """Move a plan document from inbox or outbox to trash (saves a version first). Reversible."""
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    dm = get_doc_manager()
    ok = dm.delete(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    return {"status": "trashed", "doc_id": doc_id}


@app.post("/api/plans/{doc_id}/restore-trash")
async def restore_plan_from_trash(doc_id: str) -> Dict[str, Any]:
    """Restore a plan document from trash back to inbox."""
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    dm = get_doc_manager()
    ok = dm.restore_from_trash(doc_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Plan {doc_id!r} not in trash, or already exists in inbox",
        )
    return {"status": "restored", "doc_id": doc_id}


@app.delete("/api/plans/{doc_id}/purge")
async def purge_plan(doc_id: str) -> Dict[str, Any]:
    """Permanently delete a plan document from trash. Version history is preserved."""
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    dm = get_doc_manager()
    ok = dm.purge(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not in trash")
    return {"status": "purged", "doc_id": doc_id}


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


@app.get("/api/actions")
async def list_actions() -> Dict[str, Any]:
    """Return all known Dr.Egeria commands grouped by family.

    Used by the Plan Editor command picker modal to populate the command catalog.
    Each entry: {name, family, aliases, in_catalog}
    """
    from advisor.command_keyword_index import get_command_keyword_index
    return {"families": get_command_keyword_index().all_commands()}


@app.post("/api/drafts/builder")
async def create_builder_draft(body: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new blank draft in builder mode (Plan Editor entry point).

    Body: {title: str, perspective?: str}
    Returns the draft spec with builder_mode=true and an empty command list.
    """
    from advisor.governance_draft import get_draft_manager
    title = (body.get("title") or "Untitled Plan").strip()
    perspective = body.get("perspective")
    dm = get_draft_manager()
    spec = dm.create(
        title=title,
        original_query=f"[builder] {title}",
        commands_identified=[],
        pending_questions={"required": [], "optional": []},
        pre_filled_answers={},
        mode="basic",
        perspective=perspective,
    )
    spec["phase"] = "confirm_commands"
    spec["phase_label"] = "Building plan"
    spec["builder_mode"] = True
    dm.save(spec)
    return spec


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


@app.get("/api/sessions")
async def list_sessions() -> Dict[str, Any]:
    """Return planning session transcript metadata (newest first)."""
    from advisor.session_logger import get_session_logger
    return {"sessions": get_session_logger().list_sessions()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """Return the full transcript for a planning session."""
    from fastapi import HTTPException
    from advisor.session_logger import get_session_logger
    entries = get_session_logger().load_session(session_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"session_id": session_id, "entries": entries}


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

    # Enrich valid_values for known field patterns with live Egeria data
    zone_values: list[str] = []
    tech_type_values: list[str] = []
    for a in template["attributes"]:
        name_low = a["name"].lower()
        if not a.get("valid_values") and "zone" in name_low:
            if not zone_values:
                try:
                    from advisor.egeria_context import EgeriaContext
                    zone_values = EgeriaContext().list_governance_zones()
                except Exception:
                    pass
            if zone_values:
                a["valid_values"] = zone_values
        elif not a.get("valid_values") and "deployed implementation type" in name_low:
            if not tech_type_values:
                try:
                    from advisor.egeria_context import EgeriaContext
                    tech_type_values = EgeriaContext().list_technology_types()
                except Exception:
                    pass
            if tech_type_values:
                a["valid_values"] = tech_type_values

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


@app.get("/api/egeria/zones")
async def get_governance_zones() -> Dict[str, Any]:
    """Return all governance zone names from the live Egeria instance."""
    try:
        from advisor.egeria_context import EgeriaContext
        zones = EgeriaContext().list_governance_zones()
        return {"zones": zones, "count": len(zones)}
    except Exception as exc:
        return {"zones": [], "count": 0, "error": str(exc)}


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
            response_length=len(req.response_text or ""),
            rating=rating,
            perspective=req.perspective or None,
            routing_agent=req.routing_agent or None,
            feedback_text=req.intent_override or None,  # repurpose for intent label until schema expanded
            user_comment=req.intent_override,
        )
        # Also write the full record including response_text to an extended JSONL
        try:
            import json as _json
            from pathlib import Path
            ext_path = Path("data/feedback/feedback_extended.jsonl")
            ext_path.parent.mkdir(parents=True, exist_ok=True)
            from datetime import datetime as _dt
            record = {
                "timestamp": _dt.utcnow().isoformat(),
                "query": req.query,
                "query_type": req.query_type,
                "vote": req.vote,
                "rating": rating,
                "perspective": req.perspective,
                "intent_override": req.intent_override,
                "routing_agent": req.routing_agent,
                "response_text": req.response_text,
                "triage_status": "new",
                "analysis_comments": "",
            }
            with open(ext_path, "a") as f:
                f.write(_json.dumps(record) + "\n")
        except Exception as exc:
            logger.warning(f"Extended feedback write failed: {exc}")
    except Exception as exc:
        logger.warning(f"Feedback recording failed: {exc}")
    return {"status": "ok"}


@app.get("/api/perspectives")
async def list_perspectives() -> Dict[str, Any]:
    """Return available perspectives (live from Egeria or CSV fallback)."""
    from advisor.perspective_manager import get_all
    return {"perspectives": get_all()}


@app.get("/api/feedback/extended")
async def feedback_extended() -> Dict[str, Any]:
    """Return all extended feedback records (with response_text, triage_status, etc.)."""
    import json as _json
    from pathlib import Path
    path = Path("data/feedback/feedback_extended.jsonl")
    records = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                records.append(_json.loads(line))
            except Exception:
                pass
    return {"records": records, "total": len(records)}


@app.patch("/api/feedback/extended/{idx}")
async def update_feedback_record(idx: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update triage_status or analysis_comments on a feedback record by line index."""
    import json as _json
    from pathlib import Path
    from fastapi import HTTPException
    path = Path("data/feedback/feedback_extended.jsonl")
    if not path.exists():
        raise HTTPException(status_code=404, detail="No feedback records")
    lines = path.read_text().splitlines()
    if idx < 0 or idx >= len(lines):
        raise HTTPException(status_code=404, detail=f"Record {idx} not found")
    try:
        record = _json.loads(lines[idx])
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt record")
    allowed = {"triage_status", "analysis_comments"}
    for k, v in body.items():
        if k in allowed:
            record[k] = v
    lines[idx] = _json.dumps(record)
    path.write_text("\n".join(lines) + "\n")
    return {"status": "ok", "record": record}


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
