"""
GovernancePlanAgent — orchestrates Governance Plan Document generation.

Phase 1 workflow (document generation only — no execution):
  1. Intent decomposition — LLM breaks the user description into governance objects
  2. Template selection   — _find_dre_template_raw / parse_template per object
  3. Dependency ordering  — predefined command-ordering rules
  4. Parameter extraction — LLM fills known params, marks TODO for unknowns
  5. Narrative generation — Goal / Requirements / Approach sections
  6. Document composition — assembles full GPD markdown
  7. Persistence          — DocumentManager.create() → inbox/
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


# ---------------------------------------------------------------------------
# Dependency ordering rules (lower number = must run first)
# ---------------------------------------------------------------------------

_COMMAND_ORDER_RULES: List[Tuple[str, int]] = [
    # More-specific patterns MUST come before less-specific ones (substring matching).
    ("create glossary term", 30),
    ("create glossary category", 22),
    ("create glossary", 10),
    ("create collection", 10),
    ("create project", 10),
    ("create community", 10),
    ("create governance zone", 10),
    ("create personal profile", 15),
    ("create actor profile", 15),
    ("create person role", 20),
    ("create it profile role", 20),
    ("create team role", 20),
    ("create team", 20),
    ("create governance definition", 20),
    ("create data asset", 30),
    ("create schema", 30),
    ("link term to category", 42),
    ("link term", 40),
    ("link glossary", 40),
    ("link person role appointment", 50),
    ("link person", 50),
    ("link team", 50),
    ("appointment", 50),
    ("assign", 50),
    ("classify", 55),
    ("set classification", 55),
]


def _command_order_key(command_name: str) -> int:
    """Return ordering weight for a command (lower = runs first)."""
    cn = command_name.lower().strip()
    for pattern, order in _COMMAND_ORDER_RULES:
        if pattern in cn:
            return order
    return 25


# ---------------------------------------------------------------------------
# GovernancePlanAgent
# ---------------------------------------------------------------------------

class GovernancePlanAgent:
    """
    Generates a full Governance Plan Document from a natural language description.

    Returns a standard RAGSystem result dict with query_type="plan" and a doc_id
    pointing to the saved inbox document.
    """

    def handle(self, query: str, perspective: str | None = None, mode: str = "basic") -> Dict[str, Any]:
        """Start a new conversational planning session via PlanElicitor."""
        logger.info(f"GovernancePlanAgent.handle: delegating to PlanElicitor, query={query[:80]!r}")
        try:
            from advisor.agents.plan_elicitor import get_plan_elicitor
            result = get_plan_elicitor().start(query, perspective=perspective, mode=mode)
            result.setdefault("routing_agent", "governance_plan_agent")
            return result
        except Exception as exc:
            logger.error(f"GovernancePlanAgent.handle: PlanElicitor failed: {exc}")
            return _error_result(query, f"Planning session could not be started: {exc}")

    def continue_draft(self, draft_id: str, user_response: str) -> Dict[str, Any]:
        """Route a user response to the active planning Q&A session."""
        from advisor.agents.plan_elicitor import get_plan_elicitor
        result = get_plan_elicitor().process(draft_id, user_response)
        result.setdefault("routing_agent", "governance_plan_agent")
        return result

    def back(self, draft_id: str) -> Dict[str, Any]:
        from advisor.agents.plan_elicitor import get_plan_elicitor
        result = get_plan_elicitor().back(draft_id)
        result.setdefault("routing_agent", "governance_plan_agent")
        return result

    def cancel(self, draft_id: str) -> Dict[str, Any]:
        from advisor.agents.plan_elicitor import get_plan_elicitor
        result = get_plan_elicitor().cancel(draft_id)
        result.setdefault("routing_agent", "governance_plan_agent")
        return result

    def save_and_exit(self, draft_id: str) -> Dict[str, Any]:
        from advisor.agents.plan_elicitor import get_plan_elicitor
        result = get_plan_elicitor().save_and_exit(draft_id)
        result.setdefault("routing_agent", "governance_plan_agent")
        return result

    def resume(self, draft_id: str) -> Dict[str, Any]:
        from advisor.agents.plan_elicitor import get_plan_elicitor
        result = get_plan_elicitor().resume(draft_id)
        result.setdefault("routing_agent", "governance_plan_agent")
        return result

    def restart_qa(self, draft_id: str) -> Dict[str, Any]:
        from advisor.agents.plan_elicitor import get_plan_elicitor
        result = get_plan_elicitor().restart_qa(draft_id)
        result.setdefault("routing_agent", "governance_plan_agent")
        return result

    def discard(self, draft_id: str) -> Dict[str, Any]:
        from advisor.agents.plan_elicitor import get_plan_elicitor
        result = get_plan_elicitor().discard(draft_id)
        result.setdefault("routing_agent", "governance_plan_agent")
        return result

    def save_as_template(self, draft_id: str, template_name: str) -> Dict[str, Any]:
        from advisor.governance_draft import get_draft_manager
        from advisor.governance_docs import get_doc_manager
        from advisor.plan_templates import get_template_manager
        dm = get_draft_manager()
        spec = dm.load(draft_id)
        if spec is None:
            return _error_result(draft_id, f"Draft `{draft_id}` not found.")
        doc_id = spec.get("doc_id")
        if not doc_id:
            return _error_result(draft_id, "Plan has not been generated yet — complete the Q&A first.")
        content = get_doc_manager().load(doc_id)
        if not content:
            return _error_result(draft_id, f"Plan document `{doc_id}` not found.")
        stem = get_template_manager().save(template_name, content)
        return {
            "query": f"save as template {template_name}",
            "response": f"Plan saved as template **{template_name}** (`{stem}.md`).",
            "query_type": "plan",
            "routing_agent": "governance_plan_agent",
            "draft_id": None,
            "sources": [], "num_sources": 0,
            "retrieval_time": 0.0, "generation_time": 0.0,
            "avg_relevance_score": 0.0, "context_length": 0,
        }

    def _handle_legacy_generate(self, query: str, perspective: str | None = None) -> Dict[str, Any]:
        """Original single-shot document generation (kept for direct calls)."""
        from advisor.llm_client import get_ollama_client
        from advisor.governance_docs import get_doc_manager
        from advisor.agents.dr_egeria_agent import DrEgeriaActionAgent

        llm = get_ollama_client()
        action_agent = DrEgeriaActionAgent()

        logger.info(
            f"GovernancePlanAgent._handle_legacy_generate: query={query[:80]!r}, perspective={perspective!r}"
        )

        # ------------------------------------------------------------------ #
        # Step 1: Decompose intent                                             #
        # ------------------------------------------------------------------ #
        decomp = self._decompose_intent(query, perspective, llm)
        title = decomp.get("title", "Data Management Plan")
        purpose = decomp.get("purpose", query)
        commands_spec = decomp.get("commands", [])

        if not commands_spec:
            return _error_result(
                query,
                "I couldn't identify the governance objects to create from your description. "
                "Please describe the specific items you want to set up — for example: "
                "'a glossary with terms and a data steward role'.",
            )

        # ------------------------------------------------------------------ #
        # Step 2 + 3: Template selection + dependency ordering                #
        # ------------------------------------------------------------------ #
        raw_commands: List[Dict] = []
        for spec in commands_spec:
            action = spec.get("action", "")
            display_name = spec.get("display_name", "")
            description = spec.get("description", "")
            template_parsed = self._load_template(action)
            raw_commands.append(
                {
                    "action": action,
                    "display_name": display_name,
                    "description": description,
                    "spec": spec,
                    "template_parsed": template_parsed,
                    "order": _command_order_key(action),
                }
            )

        ordered = sorted(raw_commands, key=lambda x: x["order"])

        # ------------------------------------------------------------------ #
        # Step 4: Parameter extraction                                         #
        # ------------------------------------------------------------------ #

        # Build cross-reference table: first Display Name per action family.
        # Used to seed reference attributes (e.g. Glossary Name for terms).
        _first_created: Dict[str, str] = {}
        for cmd in ordered:
            action = cmd["action"]
            dn = cmd.get("display_name") or cmd.get("description", "")
            family_key = action.split()[-1].lower()  # "Glossary", "Term" → last word
            if dn and family_key not in _first_created:
                _first_created[family_key] = dn
            # Also key by full action for exact matching
            if dn and action not in _first_created:
                _first_created[action] = dn

        _CROSS_REF_MAP: Dict[str, List[str]] = {
            # attr name → list of _first_created keys to try (in priority order)
            "Glossary Name": ["Create Glossary", "glossary"],
            "Project Name":  ["Create Campaign", "Create Project", "campaign", "project"],
            "Parent Project": ["Create Campaign", "campaign"],
        }

        filled: List[Dict] = []
        for cmd in ordered:
            params: Dict[str, Any] = {}
            template = cmd["template_parsed"]

            if template:
                try:
                    combined = f"{query}\n{cmd.get('display_name', '')}\n{cmd['description']}"
                    params = action_agent.extract_params(combined, template)
                except Exception as exc:
                    logger.warning(
                        f"GovernancePlanAgent: param extraction failed for "
                        f"{cmd['action']!r}: {exc}"
                    )

                # Seed the primary required Simple attribute (Display Name / Term Name /
                # etc.) from the decompose output if extract_params didn't fill it.
                seed_name = cmd.get("display_name") or cmd.get("description", "")
                if seed_name:
                    for attr in template["attributes"]:
                        if attr["required"] and attr["type"] in ("Simple", "simple", ""):
                            canon = attr["name"]
                            if not params.get(canon) and not params.get(canon.lower()):
                                params[canon] = seed_name
                            break

                # Seed optional Description from rationale if not already extracted.
                rationale = cmd.get("spec", {}).get("rationale", "")
                if rationale:
                    desc_attr = next(
                        (a for a in template["attributes"]
                         if a["name"].lower() == "description" and not a["required"]),
                        None,
                    )
                    if desc_attr:
                        canon = desc_attr["name"]
                        if not params.get(canon) and not params.get(canon.lower()):
                            params[canon] = rationale

                # Seed cross-reference attributes (e.g. Glossary Name on a term
                # command) from the first matching object created earlier in the plan.
                # These attrs are often optional but should be pre-filled when the
                # parent object is being created in the same plan.
                for attr in template["attributes"]:
                    candidates = _CROSS_REF_MAP.get(attr["name"], [])
                    if not candidates:
                        continue
                    canon = attr["name"]
                    if params.get(canon) or params.get(canon.lower()):
                        continue  # already filled
                    for key in candidates:
                        if key in _first_created:
                            params[canon] = _first_created[key]
                            break

            filled.append({**cmd, "params": params})

        # ------------------------------------------------------------------ #
        # Step 5: Narrative generation                                         #
        # ------------------------------------------------------------------ #
        goal, requirements, approach = self._generate_narrative(
            query, purpose, perspective, filled, llm
        )

        # ------------------------------------------------------------------ #
        # Step 6: Document composition                                         #
        # ------------------------------------------------------------------ #
        doc_content = self._compose_document(
            title=title,
            purpose=purpose,
            perspective=perspective or "Anyone",
            goal=goal,
            requirements=requirements,
            approach=approach,
            commands=filled,
        )

        # ------------------------------------------------------------------ #
        # Step 7: Save to inbox/                                               #
        # ------------------------------------------------------------------ #
        doc_manager = get_doc_manager()
        doc_id = doc_manager.create(title, doc_content)
        logger.info(f"GovernancePlanAgent: saved plan doc_id={doc_id}")

        try:
            from advisor.metrics_collector import get_metrics_collector
            families = ",".join(sorted({c["action"].split()[0] for c in filled}))
            get_metrics_collector().record_plan_event(
                doc_id, "created",
                title=title,
                command_families=families,
                perspective=perspective,
            )
        except Exception:
            pass

        nc = len(filled)
        summary = (
            f"I've created a Data Management Plan for **{title}**.\n\n"
            f"Saved to your inbox as `{doc_id}.md` "
            f"({nc} command{'s' if nc != 1 else ''} in sequence).\n\n"
            f"Review the plan below. You can ask me to make changes, add or remove commands, "
            f"or adjust any parameter values. "
            f"When you are satisfied, say **'execute the plan {doc_id}'** to submit it to Dr.Egeria.\n\n"
            f"---\n\n{doc_content}"
        )

        return {
            "query": query,
            "response": summary,
            "query_type": "plan",
            "doc_id": doc_id,
            "title": title,
            "num_commands": nc,
            "sources": [f"Dr.Egeria template: {c['action']}" for c in filled],
            "num_sources": nc,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 0.0,
            "context_length": len(doc_content),
        }

    # ---------------------------------------------------------------------- #
    # Execution (Phase 2)                                                      #
    # ---------------------------------------------------------------------- #

    def execute(
        self,
        doc_id: str,
        perspective: str | None = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute an approved plan document and append the outcome section.

        Steps:
          1. Load document from inbox
          2. Extract the Command Sequence section
          3. Submit to Dr.Egeria via DrEgeriaActionAgent.execute()
          4. Run OutcomeReporter to produce outcome section
          5. Move document to outbox with outcome appended

        Returns a standard result dict with query_type="plan_executed".
        """
        from advisor.governance_docs import get_doc_manager
        from advisor.agents.dr_egeria_agent import DrEgeriaActionAgent
        from advisor.agents.outcome_reporter import get_outcome_reporter

        doc_manager = get_doc_manager()
        plan_content = doc_manager.load(doc_id)

        if not plan_content:
            return _error_result(
                doc_id,
                f"Plan document `{doc_id}` not found in inbox. "
                f"It may have already been executed or archived.",
            )

        # Extract the Command Sequence section for execution
        command_section = self._extract_command_section(plan_content)
        if not command_section.strip():
            return _error_result(
                doc_id,
                f"Plan document `{doc_id}` has no Command Sequence section to execute.",
            )

        logger.info(
            f"GovernancePlanAgent.execute: doc_id={doc_id!r}, "
            f"dry_run={dry_run}, command_chars={len(command_section)}"
        )

        # Execute via Dr.Egeria MCP
        action_agent = DrEgeriaActionAgent()
        try:
            execution_output = action_agent.execute(
                command_section,
                directive="process",
                dry_run=dry_run,
            )
        except ConnectionError as exc:
            return _error_result(
                doc_id,
                f"Could not execute plan: Egeria MCP server is not reachable.\n\n"
                f"Ensure Dr.Egeria is running, then try again.\n\nDetails: {exc}",
            )
        except Exception as exc:
            execution_output = f"Execution error: {exc}"
            logger.error(f"GovernancePlanAgent.execute: MCP call failed: {exc}")

        if dry_run:
            return {
                "query": doc_id,
                "response": (
                    f"**Dry run — plan not submitted to Dr.Egeria.**\n\n"
                    f"Command sequence extracted from `{doc_id}`:\n\n"
                    f"```markdown\n{command_section}\n```"
                ),
                "query_type": "plan_executed",
                "doc_id": doc_id,
                "dry_run": True,
                "sources": [],
                "num_sources": 0,
                "retrieval_time": 0.0,
                "generation_time": 0.0,
                "avg_relevance_score": 0.0,
                "context_length": len(command_section),
            }

        # Generate outcome section
        reporter = get_outcome_reporter()
        outcome_md = reporter.generate(plan_content, execution_output, perspective)

        # Move to outbox with outcome appended
        moved = doc_manager.move_to_outbox(doc_id, outcome_md)
        if moved:
            logger.info(f"GovernancePlanAgent.execute: moved {doc_id} to outbox")
        else:
            logger.warning(
                f"GovernancePlanAgent.execute: could not move {doc_id} to outbox"
            )

        status_line = self._extract_status_from_outcome(outcome_md)

        try:
            from advisor.metrics_collector import get_metrics_collector
            get_metrics_collector().record_plan_event(
                doc_id, "executed",
                outcome_status=status_line,
                perspective=perspective,
            )
        except Exception:
            pass

        response = (
            f"Plan **{doc_id}** has been executed.\n\n"
            f"**Status:** {status_line}\n\n"
            f"The completed document (plan + outcome) has been saved to your outbox.\n\n"
            f"---\n\n{outcome_md}"
        )

        return {
            "query": doc_id,
            "response": response,
            "query_type": "plan_executed",
            "doc_id": doc_id,
            "dry_run": False,
            "execution_output": execution_output[:500],
            "sources": [],
            "num_sources": 0,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 0.0,
            "context_length": len(outcome_md),
        }

    @staticmethod
    def _extract_command_section(plan_content: str) -> str:
        """Return the raw text of the Command Sequence section.

        Stops at '## Outcome' (added post-execution) or end of file.
        Does NOT stop at command-name ## headers inside the section.
        """
        import re
        m = re.search(
            r'^##\s+Command Sequence\s*\n(.*?)(?=^##\s+Outcome\b|\Z)',
            plan_content,
            re.MULTILINE | re.DOTALL,
        )
        return m.group(1) if m else ""

    @staticmethod
    def _extract_status_from_outcome(outcome_md: str) -> str:
        import re
        m = re.search(r'\*\*Status:\*\*\s*(\w+)', outcome_md)
        return m.group(1) if m else "Unknown"

    # ---------------------------------------------------------------------- #
    # Intent decomposition                                                     #
    # ---------------------------------------------------------------------- #

    def _decompose_intent(
        self,
        query: str,
        perspective: str | None,
        llm,
        existing_commands: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Ask the LLM to extract the plan title, purpose, and ordered command list.

        existing_commands: commands already in the plan (for addition requests).
        Returns a dict: {title, purpose, commands: [{action, display_name, description, rationale, params}]}
        """
        perspective_hint = (
            f"The user's role is: {perspective}.\n" if perspective else ""
        )

        existing_hint = ""
        if existing_commands:
            lines = ["Commands already in the plan (do NOT repeat these):"]
            for c in existing_commands:
                lines.append(f"  - {c['action']}: {c.get('display_name', '')}")
            lines.append(
                "\nGenerate ONLY the new commands needed for the addition. "
                "Use the existing commands' display_names as parent/container names where relevant."
            )
            existing_hint = "\n".join(lines) + "\n\n"

        prompt = f"""You are a data governance planning assistant for the Egeria metadata platform.

A user has described a data management task. Extract the specific Dr.Egeria commands needed.

Common Dr.Egeria command names include:

  Glossary family:
    Create Glossary, Create Glossary Term, Create Glossary Category,
    Link Term to Category, Link Term to Glossary, Link Term-Term Relationship,
    Classify Glossary as Canonical, Classify Term as Question

  Projects family:
    Create Campaign, Create Project, Create Personal Project, Create Study Project,
    Create Task, Link Project Dependency

  IMPORTANT — SubProjects in Dr.Egeria:
    A sub-project is created using "Create Project" with parent relationship fields set ON
    the same command — there is NO separate "Link Project Hierarchy" step.
    The correct pattern for EACH sub-project is a single "Create Project" command with:
      display_name  = the sub-project name
      params.Parent ID = the parent project or campaign display_name
      params.Parent Relationship Type Name = ProjectHierarchy
    Example: user says "add sub-projects Discovery and Analysis under Finance Project"
      → Create Project: display_name="Discovery", params={{"Parent ID": "Finance Project", "Parent Relationship Type Name": "ProjectHierarchy"}}
      → Create Project: display_name="Analysis",  params={{"Parent ID": "Finance Project", "Parent Relationship Type Name": "ProjectHierarchy"}}
    Do NOT emit "Link Project Hierarchy" — it is not needed.
    Do NOT use Create Task for sub-projects. Tasks are separate leaf work items.

  Actor Manager family:
    Create Person, Create Team, Create Organization,
    Create Person Role, Create Team Role, Create Governance Role,
    Link Person Role Appointment, Link Team Role Appointment,
    Link Team Membership, Link Team Leader, Link Team Structure

  Governance Officer family:
    Create Governance Zone, Create Governance Definition, Create Governance Policy,
    Create Governance Role, Create Governance Driver, Create Business Imperative,
    Link Governance Policies, Link Governance Drivers, Link Governed By

  Collections family:
    Create Collection, Create Collection Folder, Add Member to Collection

  Data Designer family:
    Create Data Dictionary, Create Data Structure, Create Data Field,
    Create Data Class, Link Data Field, Link Data Class Composition

  Digital Product Manager family:
    Create Digital Product, Create Agreement, Create Data Sharing Agreement

  External Reference family:
    Create External Reference, Link External Reference

IMPORTANT — person role appointments:
  When a person is named as a role holder (e.g. "Tom Tally as Project Leader"):
  1. Use "Create Person Role" to define the role (e.g. "Project Leader")
  2. Use "Link Person Role Appointment" to assign the named person to that role
  Do NOT create a separate Person record unless the user asked for one.

{existing_hint}{perspective_hint}User description: "{query}"

Respond with ONLY a valid JSON object in this exact format (no extra text):
{{
  "title": "Short descriptive title (5-8 words)",
  "purpose": "One sentence summarising the goal",
  "commands": [
    {{
      "action": "Create Glossary",
      "display_name": "Finance Domain Glossary",
      "description": "One sentence describing the purpose of this specific object",
      "rationale": "Why this step is needed in the plan",
      "narrative": "1-2 sentence explanation for the plan document — what this creates and why, in plain language",
      "params": {{}}
    }},
    {{
      "action": "Create Project",
      "display_name": "Discovery",
      "description": "Initial discovery sub-project",
      "rationale": "Sub-project of the main campaign",
      "narrative": "Creates the Discovery sub-project under the main campaign.",
      "params": {{"Parent ID": "Finance Project", "Parent Relationship Type Name": "ProjectHierarchy"}}
    }},
    ...
  ]
}}

Rules:
- "display_name" is the exact name for this object. Use names from the user's description; invent a sensible placeholder only if truly unnamed.
- "narrative" is 1-2 plain-English sentences explaining what this step does and why, suitable for a reviewer who may not know Dr.Egeria.
- "params" carries pre-known field values (e.g. Parent ID for sub-projects). Use {{}} when empty.
- ONLY include objects the user explicitly mentioned, or technically required containers.
- Do NOT invent Governance Zones, categories, or any infrastructure not described by the user.
- Do NOT emit "Link Project Hierarchy" — sub-projects use "Create Project" with Parent ID instead.
- If the user names a person as a role holder, create the role + link the appointment. No separate Person record.
- Keep the command list minimal: only what the user asked for.
JSON:"""

        try:
            raw = llm.generate(prompt, temperature=0.2, max_tokens=3000)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                result = json.loads(m.group())
                # Post-process: apply deterministic validation rules
                from advisor.plan_validator import validate_commands
                cmds = result.get("commands", [])
                fixed, _, warnings = validate_commands(cmds, {})
                result["commands"] = fixed
                if warnings:
                    logger.info(
                        f"GovernancePlanAgent: validator applied {len(warnings)} fixes: {warnings}"
                    )
                return result
        except Exception as exc:
            logger.warning(f"GovernancePlanAgent: intent decomposition failed: {exc}")

        return {"title": query[:50].strip(), "purpose": query, "commands": []}

    # ---------------------------------------------------------------------- #
    # Template loading                                                         #
    # ---------------------------------------------------------------------- #

    def _load_template(self, action: str) -> Optional[Dict]:
        """
        Find and parse the best-matching basic template file for *action*.

        Returns the parsed template dict, or None if not found.
        """
        from advisor.agents.tools import _templates_root, _normalise
        from advisor.agents.dr_egeria_agent import parse_template

        root = _templates_root()
        if root is None:
            return None

        level_dir = root / "basic"
        if not level_dir.is_dir():
            level_dir = root

        query_norm = _normalise(action)
        words = [_normalise(w) for w in action.split() if len(w) > 3]

        best_score = 0
        best_file: Optional[Path] = None

        for md_file in sorted(level_dir.rglob("*.md")):
            stem_norm = _normalise(md_file.stem)
            score = 0
            if query_norm == stem_norm:
                score = 50          # exact match: highest priority
            elif query_norm in stem_norm:
                score = 40          # query is a prefix/substring of stem
            elif stem_norm in query_norm:
                score = 35          # stem is a prefix of query (less specific template)
            elif words:
                hits = sum(1 for w in words if w in stem_norm)
                if hits == len(words):
                    score = 30
                elif hits > 0:
                    score = 20 + hits
            if score > best_score:
                best_score = score
                best_file = md_file

        if best_file is None or best_score == 0:
            return None

        try:
            return parse_template(str(best_file))
        except Exception as exc:
            logger.warning(
                f"GovernancePlanAgent: failed to parse template {best_file}: {exc}"
            )
            return None

    # ---------------------------------------------------------------------- #
    # Narrative generation                                                     #
    # ---------------------------------------------------------------------- #

    def _generate_narrative(
        self,
        query: str,
        purpose: str,
        perspective: str | None,
        commands: List[Dict],
        llm,
    ) -> Tuple[str, List[str], str]:
        """
        Generate Goal (paragraph), Requirements (bullet list), and Approach (numbered list).
        """
        command_list = "\n".join(
            f"  {i + 1}. {c['action']}: {c.get('description', '')}"
            for i, c in enumerate(commands)
        )
        perspective_line = (
            f"User role: {perspective}\n" if perspective else ""
        )

        prompt = f"""Write three sections for a data management plan.

User request: "{query}"
{perspective_line}Commands to execute (in order):
{command_list}

Write these three sections in order:

GOAL:
A single paragraph explaining what this plan achieves and why.

REQUIREMENTS:
3-5 bullet points (one per line, starting with "-") listing key requirements or constraints.

APPROACH:
A numbered list matching the commands above. Each line: "N. Command Name (Family) — brief rationale".

Keep all sections concise and use plain language.

GOAL:"""

        try:
            raw = llm.generate(prompt, temperature=0.3, max_tokens=700)

            # Parse the three sections
            parts = re.split(
                r'\n(?:REQUIREMENTS?|APPROACH):\s*\n?', raw, flags=re.IGNORECASE
            )

            goal = ""
            requirements: List[str] = []
            approach = ""

            if parts:
                goal = re.sub(r'^GOAL:\s*', '', parts[0], flags=re.IGNORECASE).strip()
            if len(parts) >= 2:
                req_block = parts[1].strip()
                requirements = [
                    line.lstrip("-•*0123456789. ").strip()
                    for line in req_block.splitlines()
                    if line.strip() and len(line.strip()) > 5
                ]
            if len(parts) >= 3:
                approach = parts[2].strip()

        except Exception as exc:
            logger.warning(
                f"GovernancePlanAgent: narrative generation failed: {exc}"
            )
            goal = purpose
            requirements = []
            approach = ""

        # Fallback: build approach from command list if LLM didn't produce one
        if not approach:
            approach = "\n".join(
                f"{i + 1}. {c['action']} — {c['spec'].get('rationale', c.get('description', ''))}"
                for i, c in enumerate(commands)
            )

        if not requirements:
            requirements = [
                "All required governance objects must be created before linking steps",
                "Use consistent display names that match your organisation's naming conventions",
                "Fill in any `<!-- TODO: fill in -->` placeholders before execution",
            ]

        return goal or purpose, requirements, approach

    # ---------------------------------------------------------------------- #
    # Document composition                                                     #
    # ---------------------------------------------------------------------- #

    def _compose_command_block(
        self, cmd: Dict, step_num: int
    ) -> str:
        """Compose one annotated Dr.Egeria command block."""
        action = cmd["action"]
        # Prefer user-edited narrative, then LLM rationale, then description
        narrative = (
            cmd.get("narrative")
            or cmd.get("spec", {}).get("rationale")
            or cmd.get("rationale")
            or cmd.get("description", "")
        )
        params: Dict[str, Any] = cmd.get("params", {})
        template: Optional[Dict] = cmd.get("template_parsed")

        lines: List[str] = []

        # Narrative comment header
        comment_body = action
        if narrative:
            # Wrap long narrative at ~80 chars, indented
            wrapped = "\n     ".join(
                narrative[i:i+80] for i in range(0, len(narrative), 80)
            )
            comment_body += f"\n     {wrapped}"
        lines.append(f"<!-- Step {step_num}: {comment_body} -->")

        lines.append(f"## {action}")
        lines.append("")

        if template:
            for attr in template["attributes"]:
                attr_name = attr["name"]

                # Resolve value: direct match, then alias
                value = params.get(attr_name) or params.get(attr_name.lower())
                if value is None:
                    for alias in attr.get("alternative_labels", []):
                        if not alias:
                            continue
                        for k, v in params.items():
                            if k.lower() == alias.lower():
                                value = v
                                break
                        if value is not None:
                            break

                if attr["required"]:
                    display = str(value) if value else "<!-- TODO: fill in -->"
                    lines.append(f"### {attr_name}")
                    lines.append(display)
                    lines.append("")
                elif value:
                    lines.append(f"### {attr_name}")
                    lines.append(str(value))
                    lines.append("")
        else:
            # No template available — minimal placeholder block
            display_name = (
                cmd.get("display_name") or cmd.get("description") or "<!-- TODO: fill in -->"
            )
            lines.append(f"### Display Name")
            lines.append(display_name)
            lines.append("")

        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    def _compose_document(
        self,
        title: str,
        purpose: str,
        perspective: str,
        goal: str,
        requirements: List[str],
        approach: str,
        commands: List[Dict],
        created_by: Optional[str] = None,
    ) -> str:
        """Assemble the complete GPD markdown."""
        import os
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        creator = created_by or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"

        parts: List[str] = [
            f"# Data Management Plan: {title}",
            f"**Created:** {now}   **Last edited:** {now}   **Status:** Draft",
            f"**Created by:** {creator}   **Perspective:** {perspective}",
            f"**Purpose:** {purpose}",
            "",
            "---",
            "",
            "## Goal",
            "",
            goal,
            "",
            "## Requirements",
            "",
        ]

        for req in requirements:
            parts.append(f"- {req}")

        parts += [
            "",
            "## Approach",
            "",
            approach,
            "",
            "---",
            "",
            "## Command Sequence",
            "",
        ]

        for i, cmd in enumerate(commands):
            parts.append(self._compose_command_block(cmd, i + 1))

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_result(query: str, message: str) -> Dict[str, Any]:
    return {
        "query": query,
        "response": message,
        "query_type": "plan",
        "sources": [],
        "num_sources": 0,
        "retrieval_time": 0.0,
        "generation_time": 0.0,
        "avg_relevance_score": 0.0,
        "context_length": 0,
    }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_agent: Optional[GovernancePlanAgent] = None


def get_governance_plan_agent() -> GovernancePlanAgent:
    global _agent
    if _agent is None:
        _agent = GovernancePlanAgent()
    return _agent
