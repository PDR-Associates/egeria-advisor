# Literate Governance with Context Intelligence — Plan Proposal

> **Status:** v2 — Updated from initial review comments. Ready for second review.
>
> **What this is:** A design and phased implementation plan for a major new Egeria Advisor capability. The goal is to allow a user to describe a data management task in plain language, receive a complete, executable, and reviewable plan document, iterate on it conversationally, execute it against Egeria, and receive a verified outcome report.

---

## 1. Vision

A user should be able to describe what they want to accomplish — including their perspective, role, and purpose — and receive back a complete, structured plan document. The system will ask clarifying questions (interactively or through the document itself) to elicit context the user wishes to provide: the more context gathered, the better the plans, wording, and parameter suggestions.

Example starting point:

> *"As a data steward for the Finance division, I want to set up a glossary for the finance domain with standard terms, categories, and data steward assignments"*

The resulting document is both **human-readable** (structured narrative with rationale and context) and **machine-executable** (Dr.Egeria markdown command blocks). After execution, the document is extended with a verified outcome section — creating an auditable record of the work done.

---

## 2. Workflow

```
1. DESCRIBE    User states intent, perspective, role, and purpose
      ↓
2. CLARIFY     System asks questions to gather missing context (mini-plan agreement)
      ↓
3. PLAN        System generates a structured Plan Document
      ↓
4. REVIEW      User reads, edits, and/or requests changes (iterative)
      ↓
5. EXECUTE     User approves; system runs the document via Dr.Egeria MCP
      ↓
6. REPORT      System verifies results via report_specs, appends outcome section
      ↓
7. STORE       Final document (plan + outcome) saved to user's folder
      ↓
8. TRACK       Usage and outcome data captured for insight and improvement
```

**Step 2 (CLARIFY)** is a mini-plan agreement step: the system proposes a brief summary of what it intends to do (which objects to create, which families to use, rough sequence), and the user can agree, redirect, or add context before the full document is generated. This is not a blocking interrogation — the user can skip it and proceed directly to the plan.

---

## 3. The Plan Document

> **Naming note:** "Governance" carries negative connotations in some organisations. The document and feature will use neutral language — "Plan Document" or "Data Management Plan" — and avoid "governance" where possible in user-facing text. The internal code name remains LGCI.

The Plan Document is the central artifact. It is a single markdown file with the following sections:

### 3.1 Header
```markdown
# Data Management Plan: <task title>
**Created:** <date>   **Status:** Draft | Approved | Executed
**Requested by:** <user>   **Perspective:** <role>   **Purpose:** <stated purpose>
```

### 3.2 Goal and Requirements
Structured summary of what is to be achieved and any constraints or requirements stated by the user. Written in plain language; LLM-generated from the clarification dialogue; user can edit freely.

```markdown
## Goal
<one-paragraph statement of what this plan achieves and why>

## Requirements
- <requirement 1 — e.g. "glossary must use the Finance zone">
- <requirement 2 — e.g. "all terms must have a data steward assigned">
- <requirement 3 — ...>
```

### 3.3 Approach
Ordered summary of which Dr.Egeria command families are used and in what sequence, with a brief rationale for each step. Captures *why* a particular approach was chosen — which dependencies exist, why ordering matters, and what alternatives were considered.

```
1. Create Glossary (Glossary family) — establishes the container for Finance terms
2. Create Glossary Terms × N (Glossary family) — adds the defined terms
3. Link Term to Category (Glossary family) — organises terms by sub-domain
4. Create Governance Role (Actor Manager family) — defines the Finance data steward role
5. Link Person Role Appointment (Actor Manager family) — assigns the named steward
```

Over time, common patterns will emerge here (e.g. "Glossary setup" is always steps 1–3; "Steward assignment" is always steps 4–5). These can be captured as reusable plan templates.

### 3.4 Command Sequence
The actual Dr.Egeria markdown commands, pre-filled and ready to execute. Each command block is preceded by a comment that explains:
- What the command does in context
- Why specific parameter values were chosen
- Any relationships being established and why

Parameters extracted from the user's description and clarification dialogue are filled in. Unknown optional parameters use documented defaults. Unknown required parameters are marked `<!-- TODO: fill in -->`.

```markdown
<!-- Step 1: Create the Finance Glossary container.
     Placed in the Finance governance zone so it is visible to Finance data stewards. -->
## Create Glossary
### Display Name
Finance Domain Glossary
### Description
Canonical glossary for the Finance business domain. Owned by the Finance data governance team.
---

<!-- Step 2: Create the Revenue Recognition term.
     Linked to the Finance glossary created in step 1 by qualified name reference. -->
## Create Glossary Term
### Display Name
Revenue Recognition
...
```

### 3.5 Outcome (added post-execution)
```markdown
## Outcome
**Executed:** <date>   **Status:** Success | Partial | Failed

### Summary
<LLM-generated narrative: what was created, any warnings or partial failures>

### Verification Reports
<embedded output from relevant report_spec calls — e.g. Glossary Terms report filtered to "Finance">
```

---

## 4. Components

### 4.1 GovernancePlanAgent  `advisor/agents/governance_plan_agent.py`

Orchestrates the full plan generation lifecycle:

0. **Clarification dialogue** — Before decomposing intent, present a mini-plan and gather missing context (perspective, purpose, constraints). The user can agree and continue, or redirect. This step is skippable.
1. **Intent decomposition** — LLM breaks the confirmed intent into a list of governance objects to create/link (e.g. "1 glossary, 5 terms, 1 steward role")
2. **Template selection** — For each object, find the best-matching Dr.Egeria template (reuses `_find_dre_template_raw` with perspective boosting)
3. **Dependency ordering** — Sort commands so referenced objects are created before they are referenced (glossary before terms, role before appointment); document-scoped name references mean commands must run as a whole file
4. **Parameter extraction** — LLM fills parameters from the user description and clarification dialogue; marks unknown required params as TODO; adds rationale comments to each command block
5. **Narrative generation** — LLM writes the Goal, Requirements, and Approach sections
6. **Document composition** — Assembles the full Plan Document markdown

### 4.2 DocumentManager  `advisor/governance_docs.py`

Manages the lifecycle of Plan Documents. The storage location is **asked upfront** during first use, with defaults drawn from `advisor.yaml` (Inbox/Outbox paths) or the pyegeria configuration mechanisms. The system is multi-user aware — different users can have different storage roots.

Default folder structure:

```
{docs_root}/
  inbox/         — incoming plans awaiting review or execution (previously "pending")
  outbox/        — executed plans with outcome sections
  archived/      — superseded or cancelled plans
```

Operations: `create(title, content)`, `load(doc_id)`, `update(doc_id, content)`, `execute(doc_id)` → moves to outbox/ after run, `list()`, `archive(doc_id)`.

Storage location (from `advisor.yaml`, with fallback to pyegeria config):
```yaml
governance_plans:
  inbox:  ~/egeria-plans/inbox/    # default; overridable
  outbox: ~/egeria-plans/outbox/
```

Whether plan documents are tracked in git is the user's choice — the system neither requires nor prevents it.

### 4.3 ReviewLoop (Web UI)

The interactive refinement phase is web-first. The Plan Document is displayed in a scrollable markdown panel. Below it, a chat input allows the user to request changes ("rename the glossary to Finance Glossary 2025", "add a term for Accounts Receivable"). The system applies the change to the document and re-renders.

An **Execute** button becomes active once the user marks the document ready. A **Download** button allows saving the plan before execution.

CLI support (opening in `$EDITOR`) is deferred to Phase 3.

### 4.4 ExecutionOrchestrator  (extends existing MCP integration)

Submits the approved Plan Document's command sequence to Dr.Egeria via `dr_egeria_run_block`.

**Execution is whole-document.** Dr.Egeria processes entire markdown files, and commands within a document often reference objects created earlier in the same file by name. Splitting into individual commands would break those references. The full command sequence section is extracted from the Plan Document and submitted as one file.

### 4.5 OutcomeReporter  `advisor/agents/outcome_reporter.py`

After execution:

1. **Report selection** — Map the command families used in the plan to relevant report_specs. Since Dr.Egeria templates are already organised by family, the mapping is family-based: e.g. Glossary family → "Glossary" and "Glossary Terms" report_specs; Actor Manager family → "Person Roles" report_spec. This mapping lives in `config/governance_report_map.yaml` (a new config file, structured as `{family: [report_spec_name, ...]}`).
2. **Run reports** — Call `ReportPipeline.run_report()` for each mapped spec, using created object names as search strings to filter results to the relevant objects.
3. **Synthesise summary** — LLM generates a narrative from report output.
4. **Append outcome section** — Extends the Plan Document in place; document moves from inbox/ to outbox/.

---

## 5. Phased Implementation Plan

### Phase 1 — Document generation and review (no execution)
**Deliverable:** User can describe a task, agree on a mini-plan, receive a full Plan Document, and iterate on it conversationally via the web UI.

- [ ] `GovernancePlanAgent` — clarification dialogue → intent decomposition → template selection → ordering → parameter extraction → document composition
- [ ] Plan Document markdown composer (Goal/Requirements/Approach/Commands sections)
- [ ] `DocumentManager` — create/load/update/list (inbox/ only)
- [ ] `config/advisor.yaml` — add `governance_plans.inbox` / `governance_plans.outbox` paths
- [ ] Web UI: Plan Document display panel + chat-based refinement loop
- [ ] New routing: distinguish "plan this for me to review" (GovernancePlanAgent) from "just do it" (DrEgeriaActionAgent)
- [ ] Trigger signal: always plan first; every multi-step governance request starts with a mini-plan agreement

### Phase 2 — Execution and outcome
**Deliverable:** Full workflow end-to-end.

- [ ] ExecutionOrchestrator — extract command section, submit to `dr_egeria_run_block`
- [ ] `config/governance_report_map.yaml` — family → report_spec mapping
- [ ] `OutcomeReporter` — report selection + execution + summary synthesis
- [ ] Plan Document outcome section composer
- [ ] `DocumentManager` — move to outbox/ on success; store outcome doc
- [ ] Web UI: Execute button, outcome display, outcome doc download

### Phase 3 — Polish and insight
**Deliverable:** Production-quality flow with usage tracking.

- [ ] CLI review loop (`$EDITOR` + diff + confirm)
- [ ] Multi-session continuity (return to a pending plan in a later session)
- [ ] Partial execution handling (some commands succeeded, some failed)
- [ ] Plan versioning (track revisions made during review)
- [ ] Parameter TODO highlighting in Web UI
- [ ] Step 8 (TRACK): usage and outcome logging for insight into what tasks users are attempting, success rates, common patterns, and gaps

---

## 6. Design Decisions

All open questions from the initial draft have been resolved:

| # | Question | Decision |
|---|---|---|
| Q1 | Where does `docs_root` default to? | Ask upfront; defaults drawn from `advisor.yaml` (inbox/outbox paths) or pyegeria config. Multi-user aware. |
| Q2 | What triggers "plan" vs "act now"? | Always plan first. Every multi-step request starts with a mini-plan agreement. User can skip clarification but always gets a document to review before execution. |
| Q3 | Execution granularity | Whole-document. Document-scoped name references between commands require this. |
| Q4 | Command-family → report_spec mapping | Config file (`config/governance_report_map.yaml`). Template families already organise commands — the same family taxonomy drives report selection. |
| Q5 | CLI review loop in Phase 1? | No. Web UI only for Phase 1 and 2. CLI deferred to Phase 3. |
| Q6 | Does the Plan Document live in git? | User's choice. The system neither requires nor prevents git tracking of the storage folder. |

---

## 7. What This Reuses from the Existing System

| Existing component | How it's reused |
|---|---|
| `_find_dre_template_raw()` + perspective boosting | Template selection in GovernancePlanAgent |
| `DrEgeriaActionAgent` template parsing + parameter extraction | Extended for multi-command parameter filling |
| `ReportPipeline.run_report()` | OutcomeReporter runs verification reports |
| `QuestionSpecIndex` | Finding relevant report_specs post-execution |
| `dr_egeria_run_block` MCP tool | Unchanged execution path |
| Web UI chat + markdown rendering | Review loop UI |
| Template family taxonomy | Drives both template selection and outcome report mapping |

---

## 8. What's NOT in Scope (for now)

- Rollback / undo of executed commands (Dr.Egeria does not support this natively)
- Scheduling / deferred execution
- Multi-user real-time collaboration on a Plan Document
- Integration with external approval workflows (Jira, ServiceNow, etc.)
- Automatically detecting conflicts with existing Egeria metadata before execution
- Single-command "just do it" shortcut (all requests go through the plan-first flow)
