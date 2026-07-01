# Session & Interaction State Design

**Status:** Design only — not yet implemented. Captures the diagnosis and target
design from a review conversation (Jul 2026) before surgery begins.

## Problem 1: Plan/report mode confusion (confirmed root cause)

Symptom: user completes work in one flow (e.g. a report spec / plan draft),
switches to a different action (e.g. "run a pre-built report" from the
sidebar), and the system responds as if still inside the previous flow.

### Root cause

The frontend tracks "is a plan draft active" with a single flag,
`_activeDraftId` (`advisor/web/static/index.html:428`, mirrored to
`sessionStorage`). It is set whenever a response comes back with
`query_type: 'plan_clarification'`, and is **only** cleared when a response
comes back as `plan` (saved to inbox) or `plan_executed`
(`index.html:1099-1110`). No other user action clears it — in particular,
`runReport()` / `confirmRunReport()` / `closeSearchModal()`
(`index.html:505-543`, the "run a pre-built report" sidebar flow) never
read or clear `_activeDraftId`.

`submitQuery()` (`index.html:944-955`) always sends
`draft_id: _activeDraftId || null` in the request body regardless of what
else is being requested. So if a draft is still open (e.g. mid Q&A, not yet
saved or executed) and the user clicks a sidebar report, the request carries
**both** `intent_override: 'report'` *and* the stale `draft_id`.

On the backend, `_process_query` (`advisor/rag_system.py:388`) starts with
an unconditional `if draft_id:` branch that never consults
`intent_override` at all — this is intentional per the existing design
(`CLAUDE.md` rule 17: "all messages forwarded to PlanElicitor... regardless
of intent"). Worse, the query text built for a report run,
`"run report <name>"` (`index.html:535`), matches the exec-intent regex at
`rag_system.py:430-435` on the bare `run` alternative:

```python
>>> _exec_pattern.match("run report x")
<re.Match object; span=(0, 3), match='run'>
```

So clicking "run report X" while a stale draft is attached doesn't fall
through to chat — it hits `agent.execute(doc_id)` for the **stale draft**,
silently re-executing (or erroring on) the previous plan instead of running
the requested report.

### Contributing structural issue

There are four independent client-side "what mode are we in" flags kept in
sync only by convention: `_activeDraftId` (+ its `sessionStorage` mirror),
`PlanCanvas`'s own closure-scoped `_draftId`
(`advisor/web/static/plan_canvas.js:89-127`), `selectedIntent`
(the intent button bar), and `pendingReportName`/`pendingClarification`.
Nothing enforces they agree, and the backend has no independent way to
check — it fully trusts whatever `draft_id` the client attaches to a
request.

## Problem 2: No backend-owned session concept (concurrency/isolation)

Investigating problem 1 surfaced a related, larger gap: the backend has no
session concept at all today.

- `DraftManager` is a process-wide singleton
  (`advisor/governance_draft.py:204-210`, module-level `_dm`) writing to one
  flat shared directory, `~/egeria-plans/drafts/`.
- `draft_id` generation has no user or session scoping —
  `draft_id = f"draft_{ts}_{_slug(title)}"` (`governance_draft.py:97`), a
  timestamp + title slug. Any client that knows or guesses a `draft_id` can
  resume, edit, or execute another user's in-progress plan.
- `DocumentManager` (`advisor/governance_docs.py:39`) has the identical
  pattern: one shared `~/egeria-plans/{inbox,outbox}` regardless of caller.
  `PlanTemplateManager` and `SessionLogger` follow the same convention.
- The JWT already carries a `user_id` (`get_current_user()` /
  `advisor/auth.py`), but `/api/query` (`advisor/web/app.py:268-270`) only
  uses it as a boolean (`egeria_authenticated`) — the actual `user_id` is
  discarded, never threaded into `rag.query()`, `DraftManager`, or anywhere
  else.
- `EgeriaContext` and the MCP report agent
  (`ReportPipeline.self._agent`, lazily created in `_ensure_agent()`) are
  also global singletons authenticating as one shared service account, not
  per-user. Lower priority — flagged, not solved by this design.
- `RAGSystem`'s core query pipeline was checked and holds no mutable
  per-query instance state (no `self.current_*` / `self.session*`) — it
  appears safe to call concurrently. **The risk is concentrated in the
  draft/document/report-agent layer, not the whole RAG stack.**

### Why `user_id` scoping alone is insufficient

Demo/shared-account environments run multiple concurrent browser sessions
under the *same* `user_id`. Scoping storage by `user_id` alone would still
let two concurrent tabs of the same demo user stomp on each other's
"currently active draft" pointer. Two scoping dimensions are needed, with
different lifetimes:

| Scope | Key | Lifetime | What lives there |
|---|---|---|---|
| **User** | `user_id` (JWT `sub`) | Persistent, survives logout/browser close | Drafts (durable records), inbox/outbox plan documents, templates, session logs |
| **Session** | new `session_id` | Ephemeral, dies with the tab | Active-draft pointer, current interaction mode, pending clarification |

A draft is a **user-scoped artifact** (so closing a tab and resuming later,
or from a different tab, still finds it) but "which draft is active in this
conversation right now" is **session-scoped** (so concurrent tabs of the
same user don't collide).

## Target design

### Storage layout — namespace by user

```
~/egeria-plans/users/{user_id}/drafts/
~/egeria-plans/users/{user_id}/inbox/
~/egeria-plans/users/{user_id}/outbox/
~/egeria-plans/users/{user_id}/templates/
~/egeria-plans/users/{user_id}/sessions/     (JSONL transcripts)
```

`DraftManager`, `DocumentManager`, `PlanTemplateManager`, `SessionLogger`
each take a `user_id` at construction (or per-call) instead of resolving one
global `Path.home() / "egeria-plans"`. Same path-resolution pattern as
today (`_drafts_path()` in `governance_draft.py`, `_paths` dict in
`governance_docs.py:39-54`), just parameterized by `user_id`. These stop
being process-wide singletons and become per-user instances (or a small
cache keyed by `user_id`).

### Session store — new, small, in-memory

The app runs single-process today (`uvicorn advisor.web.app:app`, no worker
flag), so a simple in-memory store is sufficient for now:

```python
SessionState = {
    "user_id": str,
    "active_draft_id": Optional[str],
    "mode": str,           # "idle" | "draft" | "report_modal"
    "last_seen": float,
}
SESSIONS: Dict[str, SessionState]   # keyed by session_id, TTL-evicted
```

`session_id` is minted **client-side** as a UUID and stored in
`sessionStorage` (not `localStorage`) — this is already the right
primitive, since `sessionStorage` is tab-scoped and dies on tab close,
matching the desired session lifetime. Sent as a header (`X-Session-Id`) on
every request. No cookie/CORS complexity needed since JWT already handles
auth.

If this app ever moves to multi-worker or multi-instance deployment, the
in-memory dict would need to move to Redis or the deployment would need
sticky routing on `session_id`. Not needed for the current single-process
deployment.

### Routing fix

Backend stops trusting a client-sent `draft_id` as ground truth. Instead:

1. Look up `SESSIONS[session_id].active_draft_id`.
2. If the incoming request also carries an explicit `intent_override` that
   signals a mode switch (e.g. `report`), that is the backend's cue to park
   the session's active draft server-side — not something the client has to
   remember to do by clearing a JS variable.
3. `_process_query`'s `if draft_id:` branch (`rag_system.py:388`) is
   replaced by a check against the session's own active draft, not a raw
   client-supplied value.
4. The `_exec_pattern` bare-`run` false positive
   (`rag_system.py:430-435`) should also be tightened to require an object
   (`run (the )?plan`, `run it`, `execute`) regardless of the session fix —
   it's a latent bug independent of the state-machine issue.

### Known edge case (deferred, not blocking)

Two sessions of the *same* user opening the *same* draft concurrently (two
tabs, one demo login, same draft). The draft spec already has `updated_at`.
Cheap optimistic-concurrency check — reject/warn a save if the on-disk
`updated_at` moved since this session last read it — would catch silent
overwrites without building real locking/checkout UI. Treated as a
follow-on, not part of the initial surgery.

## Open question

`session_id` minting: client-generated (simplest, no extra round trip) vs.
backend-minted and handed back (more robust against a hostile/broken
client, more plumbing). Leaning client-generated given the trust model is
already JWT-based and this is an internal/demo tool, not a public API.
