# Literate Governance with Context Intelligence — Plan Proposal

> **Status:** v4 — Incorporates review comments: non-linear flow, IntentModel grounding in templates, Dr.Egeria placeholder mechanism, canvas narrative text, header fields, Plan Templates, layout decision (Option A).
>
> **What this is:** A design and phased implementation plan for a major new Egeria Advisor capability. The goal is to allow a user to describe a data management task in plain language, receive a complete, executable, and reviewable plan document, iterate on it conversationally and/or directly, execute it against Egeria, and receive a verified outcome report.

---

## 1. Vision

A user should be able to describe what they want to accomplish — including their perspective, role, and purpose — and receive back a complete, structured plan document. The system will generate a reasonable first draft immediately, then support iterative refinement through conversation and direct editing, side by side.

Example starting point:

> *"As a data steward for the Finance division, I want to set up a glossary for the finance domain with standard terms, categories, and data steward assignments"*

The resulting document is both **human-readable** (structured narrative with rationale and context) and **machine-executable** (Dr.Egeria markdown command blocks). After execution, the document is extended with a verified outcome section — creating an auditable record of the work done.

---

## 2. Design Philosophy

These principles emerged from reviewing real-world deployment experience with conversational systems and dialogue research.

### 2.1 Generate first, refine second

Users consistently prefer reacting to a proposal over answering questions before seeing anything. Systems that interrogate users before generating anything have poor completion rates and low satisfaction. The right pattern:

1. Generate a reasonable draft from minimal input
2. Show it immediately — gaps marked as placeholders
3. Let the user point at what's wrong or missing
4. Ask at most one focused question per turn when genuinely blocked

This is the pattern used by GitHub Copilot, Cursor, v0.dev, and Claude Artifacts — all of which achieve high user satisfaction precisely because they show something concrete to react to.

### 2.2 The three-question threshold

Research on task-oriented dialogue (Walker PARADISE framework; commercial data from Intercom, Typeform) consistently identifies three to four sequential questions as the point at which users abandon or disengage. A multi-step interrogation before generating anything violates this threshold badly. Slot-filling dialogue works for narrow, bounded tasks (flight booking, timer setting) but fails for open-ended planning tasks where users don't know what information they need to provide.

### 2.3 Mixed initiative

Horvitz (1999) established that users prefer systems where they can volunteer information and take initiative, not just answer questions. System-driven slot-filling feels like being cross-examined. The plan flow must allow the user to skip questions, redirect the conversation, add detail in any order, and refine either conversationally or by direct editing.

### 2.4 Conversation handles structure; canvas handles detail

These are different cognitive modes. Structural changes ("add a sub-project for data quality", "move the design phase earlier", "remove the governance zone") are natural in conversation. Field-level detail (descriptions, dates, owners, zone assignments) is better handled by clicking a field in a visible artifact. Neither should force the user into the other mode.

---

## 3. Workflow

The flow is **non-linear and re-entrant**. Users can exit and return at any point, jump back to an earlier step to change direction, add context after seeing the draft, or return from the editor to conversation. The numbered sequence below shows the natural progression, not a required order.

```
1. DESCRIBE    User states intent, perspective, role, and purpose
      ↕  (can return here at any time to change direction)
2. GENERATE    System builds IntentModel → derives commands → generates first draft
               (shown immediately in the Plan Canvas alongside the chat)
      ↕  (can return to DESCRIBE, or stay here iterating)
3. REFINE      User iterates: conversationally or by direct canvas editing
               (add/remove/reorder commands; fill in fields; both views stay in sync)
               Can jump back to step 1 or 2 at any time
      ↓
4. DOCUMENT    User requests full Plan Document (narrative + commands + rationale)
      ↓
5. EXECUTE     User approves; system runs the document via Dr.Egeria MCP
      ↓
6. REPORT      System verifies results via report_specs, appends outcome section
      ↓
7. STORE       Final document (plan + outcome) saved to user's folder
      ↓
8. TRACK       Usage and outcome data captured for insight and improvement
```

**Step 2** generates immediately from whatever is known. Gaps are shown as placeholders in the canvas, not as blocking questions. The user sees the shape of the plan before any elicitation occurs.

**Step 3** is the primary interaction. The user works in the canvas (direct editing) and/or the chat (conversational refinement) — both views are always live and in sync. There is no mode switch. At any point the user can say "I want to start over" or "let me rethink the goal" and return to step 1.

---

## 4. The IntentModel

Before mapping to Dr.Egeria commands, the system builds an **IntentModel** — a structured representation of what the user wants to achieve, expressed in domain terms rather than tool terms. This is an internal representation; users never see it directly.

```json
{
  "goal": "Set up a campaign to consolidate sales forecasting",
  "entities": {
    "campaign": {
      "name": "Sales Forecast Consolidation",
      "purpose": null,
      "leader": "Tom Tally",
      "sub_projects": [
        "Survey of Existing Systems",
        "Requirements Refinement",
        "Design Proposal"
      ]
    }
  },
  "roles": [
    {"type": "Project Leader", "holder": "Tom Tally", "scope": "campaign"}
  ],
  "open_slots": ["campaign.purpose", "campaign.start_date"]
}
```

The IntentModel serves three purposes:

1. **Better generation** — commands are derived from a structured semantic model, not extracted directly from natural language, reducing hallucination of unmentioned objects
2. **Context for additions** — when the user adds something ("also add a sub-project for design"), the system knows the parent entity name and pre-fills it
3. **Refinement tracking** — the model captures what's known, what's been asked, and what's still open, without driving a sequential Q&A

### 4.1 Grounding in Dr.Egeria templates

The slot vocabulary for each entity type — what properties it has, which are required, what relationships it supports — is derived from the **Dr.Egeria templates**, not directly from the full Egeria type system. The templates define what is currently implementable. Egeria has over 600 entity types; Dr.Egeria currently implements around a dozen command families. The IntentModel is bounded by what the templates cover.

As Dr.Egeria's template coverage grows, the IntentModel vocabulary grows with it. The `egeria_types` vector collection is a useful secondary reference for understanding the full type semantics, but the templates are the authoritative source for what the system can actually execute.

### 4.2 Command derivation and ordering

Given a populated (or partially populated) IntentModel, commands are derived using a rule set. The ordering is not arbitrary — **Dr.Egeria uses internal placeholder references** so that later commands can refer to objects created earlier in the same document. For example:

- Create Campaign in step 1 → Dr.Egeria generates an internal qualified name for it
- Create Project (sub-project) in step 4 → references the campaign by its display name; Dr.Egeria resolves this to the qualified name created in step 1
- Link Person Role Appointment in step 8 → references the role and the project by name

This means the command sequence must be a valid topological ordering of the dependency graph. Rules:

- Each entity → one or more `Create` commands
- Sub-project entities → `Create Project` with `Parent ID` and `Parent Relationship Type Name = ProjectHierarchy` baked in (single command; no separate Link step needed)
- Named role holders → `Create Person Role` + `Link Person Role Appointment`, in that order
- Required containers created before their contents (Glossary before GlossaryTerm; Campaign before its sub-Projects)
- `Link` and `Classify` commands always follow their referenced `Create` commands

The derivation is **deterministic given the IntentModel** — the LLM's job is building the model, not producing the command ordering.

---

## 5. The Plan Canvas

The Plan Canvas replaces the current full-screen Plan Editor modal. It is a **persistent side panel** — always visible alongside the chat when a plan draft is active. Both views are live and in sync; neither is the "main" interface.

### 5.1 Layout

**Option A — Even split with draggable divider** *(selected)*

A 50/50 default split with a draggable resize handle so the user can allocate more space to whichever panel they are working in. This gives equal weight to both views and lets the user adapt the layout to the current task.

```
┌─────────────────────────╫──────────────────────────────────┐
│  Chat                   ║  Plan Canvas                     │
│                         ║                                  │
│  You: "Add a sub-       ║  Sales Forecast Consolidation    │
│  project for design"    ║  ─────────────────────────────   │
│                         ║                                  │
│  Added. Pre-filled      ║  ≡  Create Campaign          ✕  │
│  parent as Sales        ║     Sales Forecast Consolidation │
│  Forecast.              ║     ─────────────────────────    │
│                         ║     [narrative: rationale text]  │
│  Anything else to       ║                                  │
│  add or change?         ║  ≡  Create Project           ✕  │
│                         ║     Survey of Existing Systems   │
│                         ║     ✓ Parent: Sales Forecast     │
│                         ║     ─────────────────────────    │
│                         ║     [narrative: optional text]   │
│                         ║                                  │
│                         ║  ≡  Create Project  ← NEW    ✕  │
│                         ║     Design Proposal              │
│                         ║     ✓ Parent: Sales Forecast     │
│                         ║                                  │
│  [input]                ║  [+ Add step]                    │
│                         ║  [Generate Plan]  [Execute]      │
└─────────────────────────╫──────────────────────────────────┘
                          ↕ drag to resize
```

Other layouts (canvas-primary 30/70, collapsible drawer) are not precluded — the draggable handle provides those naturally.

### 5.2 Canvas card behaviour

Each command card supports:

- **Drag handle (≡)** — reorder by dragging
- **↑ / ↓ arrows** — reorder via keyboard/click
- **Remove (✕)** — removes the command (with undo)
- **Expand** — inline field editing without leaving the canvas
- **Narrative text area** — freeform markdown text that can appear above or below the command fields (see 5.3)
- **Status indicator** — green check when required fields complete; amber dot when fields missing; grey when optional only
- **[+ Add step]** — inserts a new command card below (opens a command picker filtered to relevant families)

Field editing within an expanded card is the primary way to add detail. The chat handles structural changes (add, remove, reorder, change type).

### 5.3 Narrative text per command

Each command card has an optional narrative text area — editable freeform markdown that appears in the generated Plan Document above or below the command block. This serves several purposes:

- **System-generated rationale** — when a command is added (by chat or by canvas), the system generates a brief explanation of why this step is needed and what it creates. This becomes the "annotation" in the final document.
- **User instructions** — the user can add notes for whoever will review or execute the plan, e.g. *"Check with the Finance team before executing this step."*
- **TODO notes** — for steps where required fields are missing, the system can generate placeholder text: *"TODO: Confirm the project leader with the Finance governance team."*

All generated narrative text is fully editable and deletable by the user. Nothing is locked.

In the generated Plan Document, this narrative appears as the comment block above each Dr.Egeria command block (the `<!-- Step N: ... -->` annotations).

---

## 6. The Plan Document

> **Naming note:** "Governance" carries negative connotations in some organisations. The document and feature will use neutral language — "Plan Document" or "Data Management Plan" — and avoid "governance" where possible in user-facing text. The internal code name remains LGCI.

The Plan Document is the central artifact. It is a single markdown file with the following sections:

### 6.1 Header

```markdown
# Data Management Plan: <task title>
**Created:** <date>        **Last edited:** <date and time>
**Status:** Draft | Approved | Executed
**Created by:** <user>     **Perspective:** <role>
**Purpose:** <stated purpose>
```

The header captures who created the plan, when it was last modified, and the perspective and purpose — all important context for reviewers and executors who may encounter the document later.

### 6.2 Goal and Requirements

```markdown
## Goal
<one-paragraph statement of what this plan achieves and why>

## Requirements
- <requirement 1>
- <requirement 2>
```

### 6.3 Approach

Ordered summary of which Dr.Egeria command families are used and in what sequence, with a brief rationale for each step and an explanation of the dependency ordering.

### 6.4 Command Sequence

The actual Dr.Egeria markdown commands, pre-filled and ready to execute. Each command block is preceded by its narrative annotation (rationale, instructions, TODOs) which is editable in the canvas.

### 6.5 Outcome (added post-execution)

```markdown
## Outcome
**Executed:** <date>   **Status:** Success | Partial | Failed

### Summary
<LLM-generated narrative>

### Verification Reports
<embedded report output>
```

---

## 7. Plan Templates

Users can save any completed plan as a reusable **Plan Template** — the plan structure with specific values replaced by `{{placeholder}}` tokens. Starting a new plan from a template skips intent decomposition and goes directly to filling in the placeholder fields.

This is already implemented via `PlanTemplateManager` (`advisor/plan_templates.py`). Templates are stored in `~/egeria-plans/plan_templates/` and are available from the Plans sidebar.

Common use cases:
- A team repeatedly sets up glossaries with the same structure — save as "Standard Glossary Setup"
- A governance programme has a standard project structure — save as "Governance Project Template"
- A data steward runs a quarterly data quality campaign — save as "Data Quality Campaign"

---

## 8. The Artifact Canvas Pattern

The Plan Canvas is an instance of a more general interaction pattern applicable across Egeria Advisor wherever a structured artifact is being created or refined.

**The pattern applies when:**
- An interaction produces a structured artifact (plan, report spec, query result, metadata record)
- The artifact benefits from iterative refinement
- The artifact has both high-level structure and field-level detail
- Users may approach from either the conversational or the direct-editing end

### 8.1 Candidate applications

| Context | Artifact | Canvas content | Chat role |
| --- | --- | --- | --- |
| **Plan creation** | Plan Document | Command cards (ordered) with narrative and fields | Add/remove/reorder commands; structural changes |
| **Report Spec design** | Report Spec (question_spec) | Spec fields: name, query pattern, collections, perspective filter | Define the report in plain language; system proposes a spec; user refines |
| **Report execution** | Report results | Live tabular/graph output, filterable | "Show only Finance zone", "add a column for steward", follow-up questions |
| **Dr.Egeria command composition** | Single command block | Field cards for one command | "Set the zone to Finance", "what does this field mean?" |
| **Collection building** | Collection membership | Member list with metadata | "Add all assets tagged Finance", "remove anything without a steward" |
| **Governance Zone design** | Zone definition + governed assets | Zone properties + asset list | "Which assets should be in this zone?" |

### 8.2 Common component

These are all instances of the same `ArtifactCanvas` component:

```
ArtifactCanvas
  ├── artifact_type          (plan | report_spec | report_result | command | ...)
  ├── items[]                (cards or rows — the editable units)
  │     ├── type             (action name, field name, ...)
  │     ├── fields{}         (key-value, typed)
  │     ├── narrative        (freeform markdown, editable, generated or user-written)
  │     ├── status           (complete | incomplete | error)
  │     └── actions          (reorder, remove, expand, ...)
  ├── toolbar                (Add, Generate/Run, Save, Execute)
  └── sync_endpoint          (which API endpoint to write changes to)
```

The chat panel's response handler checks whether an `artifact_type` and `items` delta are present in the API response and applies them to the canvas directly — without requiring a full page refresh.

### 8.3 Report Spec design flow

*(To be specified in detail — Phase 3)*

Outline:
1. User describes a desired report in plain language
2. System proposes a draft ReportSpec in the canvas
3. User refines via chat or direct editing
4. [Run Preview] shows live results below the spec
5. User saves → spec added to report catalog

---

## 9. System Components

### 9.1 GovernancePlanAgent  `advisor/agents/governance_plan_agent.py`

Orchestrates the plan generation lifecycle:

1. **Intent capture** — LLM builds IntentModel from user description (entity types, names, relationships, open slots); bounded by the Dr.Egeria template vocabulary
2. **Command derivation** — deterministic rules map IntentModel → topologically ordered command list with pre-filled params and dependency references
3. **Narrative generation** — LLM writes Goal, Requirements, Approach sections, and per-command rationale annotations
4. **Document composition** — assembles full Plan Document markdown

### 9.2 PlanElicitor  `advisor/agents/plan_elicitor.py`

Drives the multi-turn planning flow. Phases:

| Phase | Description |
| --- | --- |
| `confirm_commands` | Shows derived command set in canvas; user confirms, adds, or removes |
| `elicit_required` | Asks about genuinely blocking missing fields (max 1–2 per turn) |
| `generate` | Composes and saves the Plan Document |
| `refine` | NL-driven iterative changes; applied to both canvas and document |
| `template_offer` | Offers to save the result as a reusable template |
| `done` | Terminal |

All phases are re-entrant. The user can jump back to `confirm_commands` from `refine`, return to conversation from the editor, or restart entirely without losing previously entered values.

### 9.3 DraftManager  `advisor/governance_draft.py`

Persists planning session state (IntentModel + commands + answers + history stack) as JSON in `~/egeria-plans/drafts/`. Supports Back navigation via history stack. Draft state survives page refresh via `sessionStorage`.

### 9.4 PlanTemplateManager  `advisor/plan_templates.py`

Saves completed plans as reusable templates with `{{placeholder}}` tokens. Lists templates in sidebar. Starting from a template skips intent decomposition.

### 9.5 DocumentManager  `advisor/governance_docs.py`

Manages the lifecycle of completed Plan Documents.

```
{docs_root}/
  inbox/           — plans awaiting review or execution
  outbox/          — executed plans with outcome sections
  archived/        — superseded or cancelled plans
  drafts/          — in-progress planning sessions (DraftManager)
  plan_templates/  — reusable plan templates (PlanTemplateManager)
```

### 9.6 Plan Canvas  `advisor/web/static/plan_canvas.js` *(to be extracted)*

Currently embedded in `plan_editor.js` and `index.html`. To be extracted as a standalone component supporting:
- Persistent side panel alongside chat (Option A, draggable divider)
- Live sync with draft spec via `/api/drafts/{id}`
- Drag-to-reorder and ↑↓ arrows
- Add / remove commands
- Inline field editing (expand card)
- Per-card narrative text (generated and user-editable)
- Status indicators (complete / incomplete / placeholder)

### 9.7 ExecutionOrchestrator  *(Phase 2)*

Submits the approved Plan Document's command sequence to Dr.Egeria via `dr_egeria_run_block`. Execution is whole-document — Dr.Egeria processes entire markdown files and commands reference objects created earlier in the same file by display name, resolved via internal placeholder mechanism.

### 9.8 OutcomeReporter  `advisor/agents/outcome_reporter.py` *(Phase 2)*

After execution: maps command families to relevant `report_specs`, runs verification reports, synthesises a narrative summary, appends outcome section to the Plan Document.

---

## 10. Phased Implementation Plan

### Phase 1 — Canvas + conversational plan generation  *(in progress)*

**Deliverable:** User can describe a task, see a live Plan Canvas alongside the chat, refine conversationally or by direct editing (including add/reorder/remove commands and per-card narrative), and generate a full Plan Document.

- [x] `GovernancePlanAgent` — intent decomposition → template selection → ordering → param extraction → document composition
- [x] `PlanElicitor` — multi-phase flow with history (Back), save & exit, cancel, discard, resume; `confirm_commands` as entry phase
- [x] `DraftManager` — create/load/update/list drafts in `~/egeria-plans/drafts/`
- [x] `DocumentManager` — create/load/update/list plans in inbox/outbox
- [x] `PlanTemplateManager` — save/load/list plan templates with `{{placeholder}}` tokens
- [x] `config/advisor.yaml` — `governance_plans` paths (inbox, outbox, archived, drafts, plan_templates)
- [x] Web UI: `confirm_commands` phase with Back/Save&Exit/Cancel navigation buttons
- [x] Web UI: Active Drafts sidebar section with resume/discard
- [x] Web UI: `_activeDraftId` persisted to `sessionStorage`; `discuss_changes` button in editor
- [x] API: `/api/drafts`, `/api/plan-templates` endpoints; `draft_id` in plan listing
- [ ] **Plan Canvas** — persistent side panel (Option A, draggable divider); drag-reorder; add/remove commands; per-card narrative text area
- [ ] **IntentModel** — replace direct LLM→commands with LLM→IntentModel→commands (deterministic derivation grounded in Dr.Egeria templates)
- [ ] **Action catalog** (`config/dr_egeria_actions.yaml`) — structured definitions with aliases, dependency rules, supersedes; replaces prompt-embedded rules
- [ ] **Post-processing validation** — deterministic rule pass (catches Link Project Hierarchy, missing containers, ordering violations)
- [ ] **Per-command narrative generation** — LLM generates rationale/instruction text for each command; shown in canvas and included in Plan Document
- [ ] Layout: split-view with draggable divider when draft active
- [ ] Header: last-edited timestamp and creator in Plan Document and editor

### Phase 2 — Execution and outcome  *(not started)*

- [ ] ExecutionOrchestrator — extract command section, submit to `dr_egeria_run_block`
- [ ] `config/governance_report_map.yaml` — family → report_spec mapping
- [ ] OutcomeReporter — report selection + execution + summary synthesis
- [ ] Plan Document outcome section composer
- [ ] DocumentManager — move to outbox on success
- [ ] Web UI: Execute button, outcome display, outcome doc download

### Phase 3 — Artifact Canvas generalisation  *(not started)*

- [ ] `ArtifactCanvas` component — extract Plan Canvas into reusable component
- [ ] Report Spec design flow — canvas + chat for creating/editing question_specs *(to be specified)*
- [ ] Report execution results in canvas — live results with conversational follow-up
- [ ] CLI review loop (`$EDITOR` + diff + confirm)
- [ ] Partial execution handling
- [ ] Plan versioning
- [ ] Step 8 (TRACK): usage and outcome logging

---

## 11. Design Decisions

| # | Question | Decision |
| --- | --- | --- |
| Q1 | Where does `docs_root` default to? | Ask upfront; defaults drawn from `advisor.yaml` (inbox/outbox paths) or pyegeria config. Multi-user aware. |
| Q2 | What triggers "plan" vs "act now"? | Always plan first. Every multi-step request starts with confirm_commands in the canvas. |
| Q3 | Execution granularity | Whole-document. Document-scoped name references between commands require this. |
| Q4 | Command-family → report_spec mapping | Config file (`config/governance_report_map.yaml`). |
| Q5 | CLI review loop in Phase 1? | No. Web UI only for Phase 1 and 2. CLI deferred to Phase 3. |
| Q6 | Does the Plan Document live in git? | User's choice. The system neither requires nor prevents it. |
| Q7 | Interrogation vs. generate-first? | Generate-first. Show a draft immediately; refine through canvas and conversation. Never ask more than 1–2 questions before showing something. |
| Q8 | Slot-filling dialogue for elicitation? | No for UX. The IntentModel uses frame semantics internally without driving a Q&A. |
| Q9 | Canvas layout? | Option A (50/50) with draggable divider. User chooses allocation. |
| Q10 | Canvas pattern scope? | General `ArtifactCanvas` in Phase 3. Plan Canvas first; Report Spec canvas second. |
| Q11 | Is the workflow strictly linear? | No. Every step is re-entrant. Users can exit, return, jump back, or redirect at any point. |
| Q12 | IntentModel slot vocabulary source? | Dr.Egeria templates (currently ~12 command families). `egeria_types` collection as reference. Grows as templates grow. |
| Q13 | Per-command narrative text? | Yes — generated by LLM and user-editable. Appears in canvas and in the Plan Document as command annotations. |
| Q14 | Plan Templates? | Yes — already implemented. Save any plan as a template; start new plans from templates. Stored in `~/egeria-plans/plan_templates/`. |

---

## 12. What This Reuses from the Existing System

| Existing component | How it's reused |
| --- | --- |
| `_find_dre_template_raw()` + perspective boosting | Template selection and IntentModel slot vocabulary |
| `DrEgeriaActionAgent` template parsing + parameter extraction | Extended for multi-command parameter filling |
| `ReportPipeline.run_report()` | OutcomeReporter runs verification reports |
| `QuestionSpecIndex` | Finding relevant report_specs post-execution |
| `dr_egeria_run_block` MCP tool | Unchanged execution path |
| Web UI chat + markdown rendering | Conversational refinement alongside canvas |
| `egeria_types` vector collection | Secondary reference for type semantics |
| Template family taxonomy | Drives template selection, dependency ordering, and outcome report mapping |
| Existing resize handle implementation | Draggable divider between chat and canvas |

---

## 13. What's NOT in Scope (for now)

- Rollback / undo of executed commands (Dr.Egeria does not support this natively)
- Scheduling / deferred execution
- Multi-user real-time collaboration on a Plan Document
- Integration with external approval workflows (Jira, ServiceNow, etc.)
- Automatically detecting conflicts with existing Egeria metadata before execution
- Single-command "just do it" shortcut (all requests go through the plan-first flow)
- Direct editing of the generated markdown (users work through the canvas or chat)
