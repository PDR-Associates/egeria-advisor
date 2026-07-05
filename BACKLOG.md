# Egeria Advisor — Backlog

Consolidated work list for the `egeria-advisor` repo.  
Status: `open` · `in-progress` · `done` · `deferred`

---

## Intent Button Redesign

See also `egeria-workspaces-fs/BACKLOG.md` IB-1 through IB-7 for the full item list.

**Goal:** Replace the current seven buttons with a cleaner four-mode model.

| Mode | Button | `intent_override` | Current state |
|---|---|---|---|
| Learn | **Explain** | `explanation` | Works; needs broader doc corpus (IX-1 to IX-5) |
| Find | **Show me** | `code_help` | Works for code; needs Dr.Egeria templates + report specs (IB-3) |
| Find | **Inspect** | `code_intel` | pyegeria only; needs all-repo expansion (IB-4) |
| Author | **Create** | `create` | Not yet implemented (IB-1) |
| Execute | **Act** | `command` | Single Dr.Egeria command only; needs report + ad-hoc (IB-2, IB-7) |
| Execute | ~~**Plan**~~ | removed | Merged into Create |
| Execute | ~~**Report**~~ | relabelled | Becomes "Run Report" label only (IB-5) |
| Diagnose | **Troubleshoot** | `debugging` | Works but untested in practice |

### IB-1 — Add `Create` intent + `CreateRouter`
**Status:** done  
**Scope:** `advisor/rag_system.py`, new `advisor/agents/create_router.py`, `advisor/web/static/index.html`

CreateRouter logic:
- Contains plan/governance/project/zone/steward/policy → PlanElicitor
- Contains report/show/list/glossar/asset/collection/project type names → ReportSpecElicitor
- Ambiguous → disambiguation response: two buttons "Governance Plan" / "Report Spec"

Remove `Plan` button from `index.html`. Map `plan` intent_override to CreateRouter (backward compatible for any saved links/scripts).

### IB-2 — Expand `Act` to cover report execution + Dr.Egeria commands
**Status:** done  
**Scope:** `advisor/rag_system.py` (Act routing block), possibly new `ActRouter`

Verb-based split inside the `command` intent block:
- SHOW / LIST / GET / FIND / DISPLAY → ReportPipeline.process()
- CREATE / UPDATE / ASSIGN / LINK / REMOVE / DELETE → DrEgeriaActionAgent

Post-run follow-up actions are **conditional on whether a spec was matched**:

| Scenario | Follow-up actions |
|---|---|
| Matched + ran an existing spec | **[Modify spec ▸]** (full spec canvas — columns + all 3 param categories) · **[Run again]** |
| Ad-hoc exec (no matching spec) | **[Save as Report Spec]** · **[Run again with filter]** |

"Modify spec" opens the full Report Spec canvas pre-populated from the matched spec.  
**Depends on RS-1** (parameter panels in canvas) — without those, "Modify spec" only exposes columns, not content_filters / shape_defaults / performance_hints.

### IB-3 — Expand `Show me` to surface Dr.Egeria templates and report specs
**Status:** open  
**Scope:** `advisor/agents/examples_agent.py`, `advisor/rag_system.py`

ExamplesAgent currently: code examples and API method listings.  
Add:
- Dr.Egeria template search (via DrEgeriaTemplateAgent or direct filesystem lookup)
- Report spec catalog search (query `list_inbox()` + match by topic/title)
- Composite response: code example + related template + related report spec

### IB-4 — Expand `Inspect` to cover all repos
**Status:** open  
**Scope:** `advisor/agents/` (code_intel agent or equivalent), vector indexing

Currently pyegeria-only. Should cover:
- egeria-workspaces FastAPI handlers, compose files
- egeria-advisor source (the advisor itself)
- egeria-java (already partially indexed in `egeria_java`)

Needs multi-repo search path; may require dedicated collections for workspaces and advisor code.

### IB-5 — Rename `Report` button → `Run Report` in UI (label only)
**Status:** done  
**Scope:** `advisor/web/static/index.html` line ~259

One-line change; do alongside IB-1 so the button set updates atomically.

### IB-6 — "Fork / Customize" per report spec in sidebar
**Status:** open  
**Scope:** `advisor/web/static/index.html` (report list rendering), `advisor/web/app.py`

Each report in the sidebar gets a small "⑂ Customize" link. Clicking it opens the Report Spec Builder pre-populated from that spec's markdown — allows users to extend an existing spec without starting from scratch.

### IB-7 — Conditional post-run follow-up actions in Act
**Status:** open  
**Scope:** `advisor/agents/report_spec_agent.py` or new ActRouter, `advisor/rag_system.py`

No pre-run disambiguation modal. After a successful run, response includes conditional nav buttons:

**Matched existing spec:**
- **[Modify spec ▸]** — opens full Report Spec canvas (columns + content_filters + shape_defaults + performance_hints) pre-populated from the matched spec. **Requires RS-1.**
- **[Run again]** — re-runs the same spec, prompts for search_string override

**Ad-hoc exec (no spec match):**
- **[Save as Report Spec]** — promotes the ad-hoc run to a catalog entry via ReportSpecElicitor.start()
- **[Run again with filter]** — re-prompts for search_string override

The `act_result` response dict should include `matched_spec_id` (populated when a spec was found) so the UI knows which set of buttons to render.

---

## Report Spec Builder

| # | Item | Status | Notes |
|---|------|--------|-------|
| RS-1 | Canvas parameter panels — Content Filters + Shape Defaults + Performance Hints sections | done | Three collapsible `<details>` sections added above column cards. Debounced PATCH on field change. |
| RS-2 | Preview mode (zero-cost stateless run, no result snapshot written) | open | Call exec but discard result; show inline in chat. |
| RS-3 | Meta-level navigation / discovery for ambiguous types ("databases") | open | RAG over `egeria_types` + `egeria_concepts`; present as structured choices. See design doc. |
| RS-4 | "Fork / Customize" entry point from sidebar (see IB-6) | open | Pre-populate elicitor from existing spec. |
| RS-5 | Master-detail parameter inheritance model | deferred | Unresolved: do detail specs inherit content_filters / shape_defaults from master? |
| RS-6 | Parameter profiles ("deep traversal", "quick lookup") | deferred | Named reusable parameter sets. |
| RS-7 | Report spec import/export — feature parity with Plans | done | Added `ReportSpecDocumentManager.import_document()` (validates via `parse_report_spec_markdown`, raises `ValueError` on malformed content — `report_spec_docs.py`), `GET /api/reports/docs/{doc_id}/export` + `POST /api/reports/specs/import` (`app.py`, mirroring the Plans endpoints), and sidebar UI: "⇧ Import" button + modal in the Custom Specs header, "⤓" export button on inbox/outbox rows (`index.html`). |

---

## Vector Index Expansion

See `egeria-workspaces-fs/BACKLOG.md` IX-1 through IX-5 for the full item list.

---

## Session & Interaction State

Full design: `docs/design/SESSION_AND_INTERACTION_STATE.md`.

Confirmed via code review (Jul 2026) that a user finishing one flow (report
spec / plan draft) and switching to another (e.g. running a pre-built report
from the sidebar) can leave the system acting on stale state from the
previous flow. The `fix/report-selection-execution-rework` merge introduced
a unified `_ctx` "authoritative task/phase state" object which is a real
structural improvement, but did not close the gap — see SS-1.

| # | Item | Status | Notes |
|---|------|--------|-------|
| SS-1 | Fix interaction-mode leak — report run doesn't clear active task context | done | `runReport()`'s `confirmRunReport()` and `setIntent()` now call `clearContext()` on mode switch (`index.html`); backend `_process_query` now clears `context.task`/`draft_id` unconditionally when `query_type_override == 'report'` (`rag_system.py:483-486`), covering both the context-task branches and the legacy `draft_id.startswith("draft_report_")` fallback. |
| SS-2 | Tighten bare-word regex false positive in `report_spec_elicitor` context routing | done | `rag_system.py:498` — tightened to `run\s+(?:the\s+)?spec\|run\s+it` (mirrors the `plan_elicitor` block's `run\s+the\s+plan` fix). `run report X` no longer matches; `run it`/`run the spec`/`execute`/`go ahead`/`proceed` still do. |
| SS-3 | Backend session store — session-scoped ephemeral interaction state | open | New `session_id`, minted client-side (UUID in `sessionStorage`, sent as `X-Session-Id` header), backend in-memory `Dict[session_id, SessionState]` (TTL-evicted). Needed because `user_id` scoping alone is insufficient — demo/shared accounts run multiple concurrent sessions under one `user_id`. Note: `session_id`/`user_id` already exist as params threaded through `_process_query` (`rag_system.py:464-465`) but only for metrics/observability — frontend never sends `session_id` today, and no storage manager uses it. |
| SS-4 | Per-user artifact directory namespacing | open | `DraftManager`, `DocumentManager`, `PlanTemplateManager`, `SessionLogger` (all under `~/egeria-plans/`) and `ReportDraftManager`, `ReportSpecDocumentManager` (under `~/egeria-reports/`, added by the Report Spec Builder work — same unscoped pattern replicated) need `user_id`-scoped roots. Currently any client that knows/guesses a `draft_id` can act on another user's draft — no ownership check exists. |
| SS-5 | Optimistic concurrency check for same-user concurrent draft edits | deferred | Two sessions of the same (demo) user editing the same draft. Spec already has `updated_at` — reject/warn a save if it moved since this session last read it. Not blocking SS-1 through SS-4. |
| SS-6 | Plan Canvas edited a stale draft copy once a document existed — reorder/notes silently didn't reach the actual document | done | `PlanCanvas.open(draftId)` now checks for an existing `doc_id` and redirects into a new document-backed mode (`openDocument()`): fetches/parses the actual plan document via `_parsePlanMarkdown()` (reused from `plan_editor.js`, purified — `_synthesizePlanMarkdown()` split into a pure `_synthesizePlanMarkdownFrom()`), and Save is now explicit (`ArtifactCanvas.autoSync: false` + `flush()`) rather than auto-syncing every edit to the draft. Also added drag-reorder to the full-screen Plan Editor's command cards (it had none) and fixed a `---` duplication bug in `_parsePlanMarkdown` that would compound on every parse→save round-trip. |
| SS-7 | "Execute" faked a chat message ("execute the plan X") instead of calling a direct endpoint — hung indefinitely (silent LLM call) whenever `context.task` happened to be `plan_elicitor` at click-time | done | Three call sites (Plan Canvas execute button, full-screen Plan Editor's `_executePlanDoc()`, sidebar inbox row's ▶ button) all sent literal chat text and relied on context/routing to correctly interpret it as an execute command rather than a plan-modification instruction — if that interception failed (e.g. `_spec_d` didn't resolve in the `plan_elicitor` context branch in `rag_system.py`), it silently fell through to `continue_draft()`, an LLM-based refinement call, with no console output until (if ever) it completed. SS-6's Canvas fix made this reachable for the first time in practice, since the Canvas no longer closes after a plan is generated, so `context.task == 'plan_elicitor'` can now be set at the exact moment "Execute" is clicked. `Validate` already called `POST /api/plans/{doc_id}/validate` directly and never had this problem — added the missing `POST /api/plans/{doc_id}/execute` to match, and switched all three call sites to it, bypassing chat-text routing entirely for this action. |
| SS-8 | `MCPClient._send_request()`'s 30s `invoke_tool()` timeout could never actually fire — a genuine, unrecoverable hang if Dr.Egeria's MCP subprocess didn't respond | done | Confirmed via `py-spy dump` on a live hang: stuck exactly in `_send_request` → `self.process.stdout.readline()`, a plain blocking call on a `subprocess.Popen` stream, called directly inside an `async def` with no thread delegation. Calling blocking I/O straight from a coroutine freezes the event loop thread itself — `asyncio.wait_for()` can only act at an actual await/cancellation point, and there wasn't one while the thread was stuck inside `readline()`, so the configured 30s timeout was silently inert regardless of how long the MCP server took (or never) to respond. Fixed by running the write and each `readline()` via `loop.run_in_executor()`, so `wait_for()`'s cancellation has something to actually interrupt. Independent of whatever caused Dr.Egeria itself to stop responding in this instance — this only makes egeria-advisor fail gracefully (a clear `MCPTimeoutError` after 30s) instead of hanging its own worker thread forever. |

---

## Done (recent)

| Item | Date | Notes |
|---|---|---|
| IB-1 — Create intent + CreateRouter | 2026-06-26 | `create_router.py`, `rag_system.py`, `index.html`, `app.py` |
| IB-2 — Act verb split (read→pipeline, write→DrEgeria) + conditional post-run buttons | 2026-06-26 | `rag_system.py`, `index.html` |
| IB-5 — Rename Report → Run Report, Plan → Create | 2026-06-26 | `index.html` |
| RS-1 — Canvas parameter panels (Content Filters / Shape Defaults / Performance Hints) | 2026-06-26 | `report_spec_canvas.js`, `index.html` |
| `validate_report_spec` — fix to check actual client class, not EgeriaTech | 2026-06-26 | `report_spec_parser.py` |
| Lifecycle fix — spec stays in inbox after execute; result snapshots in outbox | 2026-06-26 | `report_spec_docs.py`, `report_spec_agent.py` |
| Three-category parameter model (content_filters, shape_defaults, performance_hints) | 2026-06-26 | `report_draft.py`, `report_spec_elicitor.py`, `report_spec_parser.py`, `app.py` |
| Routing fix — "show X with their Y and Z" → Report Spec Builder, not pipeline | 2026-06-26 | `rag_system.py` |
| Design doc + user guide for report spec builder | 2026-06-26 | `docs/design/REPORT_SPEC_BUILDER_DESIGN.md`, `docs/user-docs/REPORT_SPEC_GUIDE.md` |
