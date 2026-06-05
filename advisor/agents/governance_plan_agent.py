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

    # ── Entity type → Dr.Egeria action mapping ──────────────────────────── #
    _ENTITY_TO_ACTION: Dict[str, str] = {
        "campaign":          "Create Campaign",
        "project":           "Create Project",
        "sub_project":       "Create Project",
        "personal_project":  "Create Personal Project",
        "study_project":     "Create Study Project",
        "task":              "Create Task",
        "glossary":          "Create Glossary",
        "glossary_term":     "Create Glossary Term",
        "glossary_category": "Create Glossary Category",
        "team":              "Create Team",
        "organization":      "Create Organization",
        "collection":        "Create Collection",
        "governance_zone":   "Create Governance Zone",
        "governance_policy": "Create Governance Policy",
        "governance_definition": "Create Governance Definition",
        "data_dictionary":   "Create Data Dictionary",
        "data_structure":    "Create Data Structure",
        "data_field":        "Create Data Field",
        "data_class":        "Create Data Class",
        "digital_product":   "Create Digital Product",
        "agreement":         "Create Agreement",
        "external_reference": "Create External Reference",
    }

    def _decompose_intent(
        self,
        query: str,
        perspective: str | None,
        llm,
        existing_commands: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Two-stage decomposition:
          Stage 1 (LLM)  — extract entities and roles from natural language
          Stage 2 (rules) — map entities → Dr.Egeria commands deterministically

        This split keeps the LLM prompt simple enough for local 8B models while
        ensuring command names and structure are correct by construction.

        existing_commands: commands already in the plan (for addition requests).
        Returns a dict: {title, purpose, commands, validator_warnings}
        """
        perspective_hint = f"User role: {perspective}.\n" if perspective else ""

        existing_hint = ""
        if existing_commands:
            lines = ["Already in the plan — do NOT include these again:"]
            for c in existing_commands:
                lines.append(f"  - {c.get('display_name', '?')} ({c['action']})")
            lines.append("Add ONLY new objects the user is now requesting.")
            existing_hint = "\n".join(lines) + "\n\n"

        # ── Stage 1: entity extraction ──────────────────────────────────── #
        # Try pattern-based extraction first (reliable for common phrasings),
        # fall back to LLM for complex cases.
        entities = self._extract_entities_patterns(query)
        if not entities.get("objects"):
            entities = self._extract_entities_llm(
                query, perspective_hint, existing_hint, llm
            )
        if not entities.get("objects"):
            entities = {"title": query[:50], "purpose": query, "objects": [], "roles": []}

        # ── Stage 2: deterministic command mapping ──────────────────────── #
        commands = self._entities_to_commands(entities, existing_commands or [])

        # Apply post-processing validator
        from advisor.plan_validator import validate_commands
        commands, _, warnings = validate_commands(commands, {})
        if warnings:
            logger.info(f"GovernancePlanAgent: validator fixes: {warnings}")

        return {
            "title":              entities.get("title", query[:50]).strip(),
            "purpose":            entities.get("purpose", query),
            "commands":           commands,
            "validator_warnings": warnings,
        }

    # Name stops at these words (sentence-level boundaries)
    _NAME_STOP = r'(?=\s*(?:,|\.|\bwith\b|\bto\s+be\b|\bled\s+by\b|\bto\s+create\b|\band\b|\bincluding\b|\bwhere\b|\busing\b|$))'

    # Pattern vocab: (regex, entity_type) — name captured in group 1
    _ENTITY_PATTERNS = [
        # "called <name>" / "named <name>"
        (r'\b(?:project|campaign|glossary|collection)\s+(?:called|named)\s+"?(.+?)"?' + _NAME_STOP, None),
        # "a campaign for <name>"
        (r'\ba\s+campaign\s+for\s+"?(.+?)"?' + _NAME_STOP, "campaign"),
        # "a project for / project called"
        (r'\ba\s+project\s+(?:for|called)\s+"?(.+?)"?' + _NAME_STOP, "project"),
        # "a glossary for / called"
        (r'\ba\s+glossary\s+(?:for|called)\s+"?(.+?)"?' + _NAME_STOP, "glossary"),
        # "set up a glossary" — name after "for" or "called"
        (r'\bset\s+up\s+a\s+(?:glossary|project|campaign)\s+(?:for\s+the\s+|for\s+|called\s+)?"?(.+?)"?' + _NAME_STOP, None),
    ]
    # Role: "led by <person> as <role>" or "with <person> as <role>"
    _ROLE_PATTERNS = [
        r'\b(?:to\s+be\s+)?led\s+by\s+"?([A-Z][a-zA-Z\s\.]{1,30}?)"?\s+as\s+(?:the\s+)?([\w\s]{2,30})',
        r'\b(?:to\s+be\s+)?led\s+by\s+"?([A-Z][a-zA-Z\s\.]{1,30}?)"?' + _NAME_STOP,
        r'\bwith\s+"?([A-Z][a-zA-Z\s\.]{1,30}?)"?\s+as\s+(?:the\s+)?([\w\s]{2,30})',
    ]
    _SUBPROJECT_PATTERN = re.compile(
        r'\bsub[-\s]?projects?\s+(?:for\s+)?["\']?(.+?)(?=["\']?\s*(?:$|\.|,\s*(?:led|with|and\s+[a-z])))',
        re.IGNORECASE,
    )

    def _extract_entities_patterns(self, query: str) -> Dict:
        """
        Rule-based entity extraction for common phrasings.
        Returns entities dict if confident; empty objects list if not matched.
        """
        q = query.strip()
        objects = []
        roles   = []

        ql = q.lower()

        def _infer_type_from_context() -> str:
            if "campaign" in ql:   return "campaign"
            if "glossary" in ql:   return "glossary"
            if "collection" in ql: return "collection"
            return "project"

        # Detect main entity type and name
        main_type = ""
        main_name = ""
        for pattern, etype in self._ENTITY_PATTERNS:
            m = re.search(pattern, q, re.IGNORECASE)
            if m:
                main_name = m.group(1).strip().strip('"\'')
                if etype:
                    main_type = etype
                else:
                    # Infer from the matched text or surrounding context
                    matched_lower = m.group(0).lower()
                    if "campaign" in matched_lower:   main_type = "campaign"
                    elif "glossary" in matched_lower: main_type = "glossary"
                    else:                             main_type = _infer_type_from_context()
                break

        if not main_name:
            return {"objects": [], "roles": []}

        objects.append({"type": main_type or "project", "name": main_name})

        # Sub-projects
        sub_m = self._SUBPROJECT_PATTERN.search(q)
        if sub_m:
            sub_text = sub_m.group(1)
            # Split on commas, "and", quotes
            sub_names = re.split(r'",?\s+"|\s*,\s*|\s+and\s+', sub_text)
            for sn in sub_names:
                sn = sn.strip().strip('"\'').strip()
                if sn and sn.lower() != main_name.lower():
                    objects.append({"type": "sub_project", "name": sn, "parent": main_name})

        # Role assignments
        for pattern in self._ROLE_PATTERNS:
            m = re.search(pattern, q, re.IGNORECASE)
            if m:
                person = m.group(1).strip().strip('"\'')
                role   = (m.group(2).strip().title()
                          if m.lastindex and m.lastindex >= 2 and m.group(2)
                          else "Project Leader")
                if person and 1 <= len(person.split()) <= 5:
                    roles.append({"role": role, "person": person})
                    break

        title = f"{main_name} {main_type.title()} Setup" if main_name else query[:50]
        return {
            "title":   title,
            "purpose": f"Set up a {main_type} called {main_name}",
            "objects": objects,
            "roles":   roles,
        }

    def _extract_entities_llm(
        self, query: str, perspective_hint: str, existing_hint: str, llm
    ) -> Dict:
        """LLM-based entity extraction — fallback when pattern matching fails."""
        prompt = f"""Extract ALL objects and role assignments from this request.
Return ONLY valid JSON. Each distinct named object appears EXACTLY ONCE.

Object types: campaign, project, sub_project (child of another), glossary,
  glossary_term, glossary_category, team, collection, governance_zone

For sub_project, include "parent" with the parent's name from the request.
"name" must be copied EXACTLY from the request text — never use the type word as the name.

{existing_hint}{perspective_hint}Request: "{query}"

Return:
{{
  "title": "short title",
  "purpose": "one sentence",
  "objects": [{{"type": "...", "name": "exact name from request"}}],
  "roles": [{{"role": "role title", "person": "person name"}}]
}}
JSON:"""
        try:
            raw = llm.generate(prompt, temperature=0.0, max_tokens=700)
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw.strip())
            m   = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                raise ValueError("no JSON in LLM output")
            return json.loads(_extract_balanced_json(m.group()))
        except Exception as exc:
            logger.warning(f"GovernancePlanAgent: LLM extraction failed: {exc}")
            return {"objects": [], "roles": []}

    def _entities_to_commands(
        self, entities: Dict, existing_commands: List[Dict]
    ) -> List[Dict]:
        """
        Deterministically map extracted entities and roles to Dr.Egeria commands.
        """
        from advisor.action_catalog import get_action_catalog
        catalog = get_action_catalog()
        commands: List[Dict] = []
        existing_names = {c.get("display_name", "").lower() for c in existing_commands}

        def _make_cmd(action: str, display_name: str, pre_filled: Optional[Dict] = None,
                      narrative: str = "") -> Dict:
            return {
                "action":       action,
                "display_name": display_name,
                "description":  "",
                "rationale":    "",
                "narrative":    narrative or catalog.narrative_template(action),
                "pre_filled":   pre_filled or {},
                "placeholders": {},
            }

        # Identify the top-level container (campaign or first unparented project)
        # so we can infer parent for unparented sub-items
        top_level_name = ""
        for obj in entities.get("objects", []):
            otype = (obj.get("type") or "").lower()
            if otype in ("campaign",):
                top_level_name = (obj.get("name") or "").strip()
                break
        if not top_level_name:
            # Also check existing commands for a campaign/top-level project
            for ec in existing_commands:
                if ec.get("action") in ("Create Campaign", "Create Project") \
                        and not (ec.get("pre_filled") or {}).get("Parent ID"):
                    top_level_name = ec.get("display_name", "")
                    break

        for obj in entities.get("objects", []):
            entity_type = (obj.get("type") or "").lower().replace("-", "_").replace(" ", "_")
            name = (obj.get("name") or "").strip()
            if not name or name.lower() in existing_names:
                continue

            # A "project" with a parent field is implicitly a sub-project
            parent = (obj.get("parent") or "").strip()
            if parent and entity_type == "project":
                entity_type = "sub_project"

            # Unparented projects when a campaign exists → infer as sub-projects
            if entity_type == "project" and not parent and top_level_name \
                    and name != top_level_name:
                parent = top_level_name
                entity_type = "sub_project"

            action = self._ENTITY_TO_ACTION.get(entity_type)
            if not action:
                action = catalog.find_by_alias(entity_type) or "Create Project"

            pre_filled: Dict[str, str] = {"Display Name": name}
            if parent and entity_type == "sub_project":
                pre_filled["Parent ID"] = parent
                pre_filled["Parent Relationship Type Name"] = "ProjectHierarchy"

            commands.append(_make_cmd(action, name, pre_filled))

        for role in entities.get("roles", []):
            # Accept both "role" and "role_name" as field names
            role_title  = (role.get("role") or role.get("role_name") or "").strip().title()
            person_name = (role.get("person") or role.get("person_name") or "").strip()
            if not role_title:
                continue

            commands.append(_make_cmd(
                "Create Person Role", role_title,
                {"Display Name": role_title},
            ))
            if person_name:
                commands.append(_make_cmd(
                    "Link Person Role Appointment", "",
                    {"role_name": role_title, "person_name": person_name},
                ))

        return commands

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
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_balanced_json(raw: str) -> str:
    """
    Find the outermost balanced {...} object in raw, even if the LLM appended
    trailing text or commentary after the closing brace.
    """
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(raw):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_str:
            escape = True
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return raw[:i + 1]
    return raw  # fallback: return as-is


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_agent: Optional[GovernancePlanAgent] = None


def get_governance_plan_agent() -> GovernancePlanAgent:
    global _agent
    if _agent is None:
        _agent = GovernancePlanAgent()
    return _agent
