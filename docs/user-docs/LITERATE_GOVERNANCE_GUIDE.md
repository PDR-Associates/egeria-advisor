# Literate Governance Guide

Egeria Advisor can turn a plain-language description of a data management task into a
complete, reviewable, executable plan — and then verify that the work was done.

This feature is called **Literate Governance with Context Intelligence (LGCI)**.
It is named after *Literate Programming*: the idea that intent, approach, and executable
commands live together in one human-readable document.

---

## What it does

You describe what you want to accomplish. The advisor:

1. **Plans** — generates a structured markdown document with goal, approach, and
   pre-filled Dr.Egeria commands
2. **Reviews** — shows you the plan inline; you can ask for changes conversationally
3. **Executes** — submits the approved plan to Dr.Egeria via MCP
4. **Reports** — verifies what was created, appends an outcome section, saves to outbox

---

## When to use it

Use Literate Governance when you want to:

- Set up a **new glossary** with terms, categories, and steward assignments
- Create a **governance structure** (zones, policies, roles, appointments)
- Define a **data dictionary** with fields, data classes, and classifications
- Build a **project** with tasks and team assignments
- Do anything that requires **multiple related Dr.Egeria commands in sequence**

Use plain Dr.Egeria commands (Act intent) instead when you want to create or update
a **single object** (one glossary, one term, one zone).

---

## Triggering a plan

Describe what you want to accomplish in natural language. Multi-step requests are
automatically routed to the plan generator:

```
"I want to set up a glossary for the finance domain with standard terms,
 categories, and data steward assignments"

"Set up a governance structure for the HR division including governance zones,
 policies, and a governance officer role"

"Create a data dictionary for customer data with fields, data classes,
 and appropriate governance classifications"

"Plan to set up a project for the Q3 data quality initiative with tasks and
 team assignments"
```

**Tips for triggering a plan:**
- Include phrases like *"set up"*, *"plan to"*, *"with … and …"*, or describe
  multiple objects in one request
- Be specific about the domain, purpose, and who owns the data — the more context
  you give, the better the parameter suggestions

**What does NOT trigger a plan:**
- *"Create a glossary"* — single object, goes to DrEgeriaActionAgent directly
- *"Give me a Dr.Egeria template for a glossary"* — returns the template only
- *"List glossaries"* — a report query

---

## Reading the plan document

The plan is displayed inline in the chat as a markdown document with five sections:

### 1. Header
```
# Data Management Plan: Finance Domain Glossary
**Created:** 2026-06-02   **Status:** Draft
**Requested by:** Dan Wolfson   **Perspective:** Data Steward
**Purpose:** Establish canonical glossary for Finance business domain
```

### 2. Goal and Requirements
Plain-language statement of what the plan achieves and any constraints.

### 3. Approach
Ordered summary of which Dr.Egeria command families will be used and why —
for example: *"1. Create Glossary (Glossary family) — establishes the container…"*

### 4. Command Sequence
The actual Dr.Egeria markdown commands, pre-filled where possible. Parameters
the advisor couldn't determine are marked with an orange **⚠ fill in** badge.
These must be filled in before executing.

### 5. Outcome (added after execution)
Automatically appended when the plan is executed — includes execution status,
a narrative summary, and embedded verification report output.

---

## TODO markers

When a required parameter cannot be determined from your description, the plan
marks it with `<!-- TODO: fill in -->` rendered as an **⚠ fill in** badge.

To fill these in, ask the advisor conversationally:

```
"Change the glossary name to Finance Glossary 2026"
"Set the data steward to erinoverview"
"Add a description: Canonical glossary for Finance business domain"
```

Or use the CLI to open the plan in your editor (see [CLI tools](#cli-tools) below).

---

## Refining the plan

While a plan is in your inbox (before execution), you can ask for changes:

```
"Add a term for Revenue Recognition"
"Remove the team membership step — we don't need that"
"Change the governance zone to Finance-Prod"
"Add a second data steward role for the EMEA region"
```

The advisor modifies the plan document and saves the updated version. The previous
version is automatically backed up to `~/egeria-plans/versions/`.

---

## Executing the plan

When you are satisfied with the plan:

1. Click the **Execute** button in the violet banner below the plan text
2. Or type: `execute the plan {doc_id}` (the doc_id is shown in the banner)

The plan is submitted to Dr.Egeria as a single markdown file. All commands run
in sequence; later commands can reference objects created earlier in the same file
by display name.

**Dry run** (CLI only): `egeria-advisor-plans execute {doc_id} --dry-run`
Shows the extracted command sequence without submitting it to Dr.Egeria.

---

## Reviewing the outcome

After execution the advisor:

1. Runs verification reports for the command families used (e.g. *Glossaries*,
   *Glossary-Terms* for Glossary family commands)
2. Synthesises a narrative summary
3. Appends a **## Outcome** section to the plan document
4. Moves the document from `inbox/` to `outbox/`

The outcome section shows:
- **Status**: Success / Partial / Failed / Unknown
- **Summary**: LLM-generated narrative of what was created
- **Command Results** (on Partial/Failed): per-command success/failure table
- **Execution Output**: raw Dr.Egeria output (truncated)
- **Verification Reports**: embedded report output filtered to created objects

---

## Multi-session continuity

Plans persist between sessions. The **Plans** sidebar (left panel, middle section)
lists all plans in your inbox and outbox.

- Click an **inbox** plan to restore it into the chat with its Execute button
- Click an **outbox** plan to review the completed plan + outcome

The sidebar refreshes automatically after each plan lifecycle event.

---

## Where plans are stored

| Folder | Contents |
|--------|----------|
| `~/egeria-plans/inbox/` | Plans awaiting review or execution |
| `~/egeria-plans/outbox/` | Executed plans with outcome section appended |
| `~/egeria-plans/archived/` | Cancelled or superseded plans |
| `~/egeria-plans/versions/` | Automatic backups saved before each edit |

Paths are configurable in `config/advisor.yaml`:

```yaml
governance_plans:
  inbox:    ~/egeria-plans/inbox/
  outbox:   ~/egeria-plans/outbox/
  archived: ~/egeria-plans/archived/
```

Plan documents are markdown files named `{YYYYMMDD_HHMMSS}_{title-slug}.md`.
They are plain files — you can track them in git, share them, or edit them
with any markdown editor.

---

## CLI tools

The `egeria-advisor-plans` command provides a full review loop from the terminal:

```bash
# List plans in your inbox
egeria-advisor-plans list

# List inbox and outbox
egeria-advisor-plans list --outbox

# Print a plan with ⚠ fill in markers highlighted
egeria-advisor-plans show 20260602_143022_finance_glossary

# Open in $EDITOR, show a coloured diff, confirm before saving
egeria-advisor-plans edit 20260602_143022_finance_glossary

# Execute a plan (submits to Dr.Egeria)
egeria-advisor-plans execute 20260602_143022_finance_glossary

# Execute without submitting (shows extracted commands only)
egeria-advisor-plans execute 20260602_143022_finance_glossary --dry-run

# List saved edit backups
egeria-advisor-plans versions 20260602_143022_finance_glossary
```

---

## Full example walkthrough

**Step 1 — Describe the task**

> *"As a data steward for the Finance division, I want to set up a glossary for
> the finance domain with standard terms, categories, and data steward assignments"*

**Step 2 — Review the plan**

The advisor generates a plan document. Check:
- Are the display names right?
- Are there any **⚠ fill in** markers that need your attention?
- Does the approach match what you intended?

Ask for changes if needed:
> *"Change the glossary name to Finance Terms 2026"*

**Step 3 — Execute**

Click **Execute**. The advisor submits the commands to Dr.Egeria.

**Step 4 — Review the outcome**

The outcome section appears inline. Check the Status and the verification report
to confirm the objects were created correctly.

**Step 5 — Find it later**

The completed plan is in your outbox. Click it from the Plans sidebar to review.

---

## Troubleshooting

**"I described a complex task but got a single Dr.Egeria command instead of a plan"**

The routing threshold for plan vs. single command is: does the request involve
multiple objects or families? Try making the request explicitly multi-step:
> *"Set up a glossary **with** terms, categories, **and** steward assignments"*
> (the *"with … and …"* pattern reliably triggers the plan generator)

**"The plan has many ⚠ fill in markers"**

This means the advisor couldn't extract those values from your description.
Provide more context upfront, or fill them in conversationally after generation.

**"Execution failed with status Partial"**

Some commands succeeded and some did not. Check the **Command Results** table
in the outcome section to see which ones failed. Common causes:
- A referenced object doesn't exist yet (e.g. a governance zone that needs to
  be created first in a separate step)
- Missing required field that was left as `<!-- TODO: fill in -->`

**"The plan is in outbox but I want to re-execute"**

Outbox plans are immutable. Generate a new plan from the same description,
or copy the command sequence from the outbox document into a new Dr.Egeria run.
