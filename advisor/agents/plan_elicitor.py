"""
PlanElicitor — conversational Q&A engine for Governance Plan generation.

Drives the multi-phase planning flow:
  confirm_commands → show proposed command set; ask user to confirm or extend
  elicit_required  → ask about missing required template fields
  elicit_optional  → offer optional fields (basic/advanced mode)
  generate         → compose and save the plan document
  refine           → NL-driven iterative change loop
  template_offer   → offer to save the result as a reusable template
  done             → terminal state

Each phase returns a standard result dict with query_type="plan_clarification"
and navigation metadata so the UI can render Back / Save & Exit / Start Over buttons.

The DraftManager handles all persistence; this module is stateless between calls.
"""
from __future__ import annotations

import json
import re
import copy
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from advisor.governance_draft import DraftManager, get_draft_manager
from advisor.plan_templates import get_template_manager

# Navigation button sets per phase
_NAV_FIRST  = ["save_exit", "cancel"]          # first step — no Back
_NAV_MIDDLE = ["back", "save_exit", "cancel"]  # mid-flow
_NAV_FINAL  = ["back", "cancel"]               # last step — no Save & Exit (plan already in inbox)

_PHASE_LABELS = {
    "confirm_commands": "Confirming plan steps",
    "elicit_required":  "Answering required field questions",
    "elicit_optional":  "Choosing optional fields",
    "generate":         "Ready to generate plan",
    "refine":           "Reviewing and refining the plan",
    "template_offer":   "Offering template save",
    "done":             "Complete",
}


# ---------------------------------------------------------------------------
# Public entry points (called from GovernancePlanAgent)
# ---------------------------------------------------------------------------

class PlanElicitor:
    """Drives the multi-turn planning Q&A flow."""

    # ------------------------------------------------------------------
    # Phase 1 — start a new elicitation session
    # ------------------------------------------------------------------

    def start(
        self,
        query: str,
        perspective: Optional[str],
        mode: str = "basic",
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Decompose the user's intent, pre-fill what we can from the query,
        save a draft spec, and return the confirm_commands response.

        The first response shows the proposed command set (with template-informed
        field status) and asks the user to confirm or extend before any field
        elicitation begins.
        """
        from advisor.llm_client import get_planning_llm
        from advisor.agents.governance_plan_agent import GovernancePlanAgent

        llm = get_planning_llm()
        agent = GovernancePlanAgent()

        # --- Decompose intent ------------------------------------------
        _val_warnings: List[str] = []
        if template_name:
            commands = get_template_manager().template_to_commands(template_name)
            title = template_name
            purpose = query
        else:
            decomp = agent._decompose_intent(query, perspective, llm)
            title = decomp.get("title", query[:50])
            purpose = decomp.get("purpose", query)
            _val_warnings = decomp.get("validator_warnings") or []
            from advisor.action_catalog import get_action_catalog
            catalog = get_action_catalog()
            commands = [
                {
                    "action":       c.get("action", ""),
                    "display_name": c.get("display_name", ""),
                    "description":  c.get("description", ""),
                    "rationale":    c.get("rationale", ""),
                    # narrative: prefer LLM-generated, fall back to catalog template
                    "narrative":    (
                        c.get("narrative", "")
                        or catalog.narrative_template(c.get("action", ""))
                    ),
                    "pre_filled":   dict(c.get("params") or {}),
                    "placeholders": {},
                }
                for c in decomp.get("commands", [])
                if c.get("action")
            ]

        if not commands:
            return _error_result(
                query,
                "I couldn't identify specific Dr.Egeria commands from your description.\n\n"
                "Try being more specific — for example:\n"
                "> *\"Set up a glossary called Finance Terms with five terms and a data steward\"*",
            )

        # --- Pre-fill names and values from the query text -------------
        pre_filled = self._pre_fill(query, commands, llm)
        for cmd in commands:
            action_fills = pre_filled.get(cmd["action"], {})
            cmd["pre_filled"].update(action_fills)
            if cmd.get("display_name") and "Display Name" not in cmd["pre_filled"]:
                cmd["pre_filled"]["Display Name"] = cmd["display_name"]

        # Build initial answers from pre_filled (pending_questions deferred
        # until after the user confirms the command set)
        answers: Dict[str, Dict[str, str]] = {}
        for cmd in commands:
            if cmd["pre_filled"]:
                answers[cmd["action"]] = dict(cmd["pre_filled"])

        dm = get_draft_manager()
        spec = dm.create(
            title=title,
            original_query=query,
            commands_identified=commands,
            pending_questions={"required": [], "optional": []},
            pre_filled_answers=answers,
            mode=mode,
            perspective=perspective,
            template_name=template_name,
        )
        # Override the default phase set by DraftManager.create
        spec["phase"] = "confirm_commands"
        spec["phase_label"] = _PHASE_LABELS["confirm_commands"]
        dm.save(spec)

        # Log session start
        try:
            from advisor.session_logger import get_session_logger
            import os
            sl = get_session_logger()
            sl.log_turn(
                spec["draft_id"], role="user", content=query,
                phase="confirm_commands", perspective=perspective,
                metadata={
                    "user": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
                    "mode": mode,
                    "template_name": template_name,
                    "commands_count": len(commands),
                },
            )
        except Exception:
            pass

        # Surface any auto-corrections made by the validator
        init_note = None
        if _val_warnings:
            init_note = "Auto-corrected: " + "; ".join(_val_warnings)

        return self._build_confirm_commands_response(spec, note=init_note)

    # ------------------------------------------------------------------
    # Phase dispatch — continue an existing draft
    # ------------------------------------------------------------------

    def process(self, draft_id: str, user_response: str) -> Dict[str, Any]:
        """
        Receive a user message for an active draft and advance the phase.
        """
        dm = get_draft_manager()
        spec = dm.load(draft_id)
        if spec is None:
            return _error_result(
                draft_id,
                f"Draft `{draft_id}` not found. It may have been discarded. "
                f"Start a new plan by describing what you want to set up.",
            )

        # Log the user turn
        try:
            from advisor.session_logger import get_session_logger
            get_session_logger().log_turn(
                draft_id, role="user", content=user_response,
                phase=spec.get("phase"),
                perspective=spec.get("perspective"),
            )
        except Exception:
            pass

        phase = spec.get("phase", "confirm_commands")

        if phase == "confirm_commands":
            result = self._handle_confirm_commands(spec, user_response)
        elif phase == "elicit_required":
            result = self._handle_elicit_required(spec, user_response)
        elif phase == "elicit_optional":
            result = self._handle_elicit_optional(spec, user_response)
        elif phase == "generate":
            result = self._handle_post_generate(spec, user_response)
        elif phase == "refine":
            result = self._handle_refine(spec, user_response)
        elif phase == "template_offer":
            result = self._handle_template_offer(spec, user_response)
        else:
            result = _error_result(draft_id, f"Unknown draft phase: {phase!r}")

        # Log system response and finalize session on terminal states
        self._log_system_response(draft_id, spec, result)
        return result

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------

    def back(self, draft_id: str) -> Dict[str, Any]:
        """Rewind one step in the history stack."""
        dm = get_draft_manager()
        spec = dm.load(draft_id)
        if spec is None:
            return _error_result(draft_id, f"Draft `{draft_id}` not found.")

        if not dm.pop_history(spec):
            return _clarification_result(
                spec,
                "You're already at the beginning — there's nowhere to go back to.\n\n"
                + self._format_current_state(spec),
                phase_override="elicit_required",
                can_go_back=False,
                nav=_NAV_FIRST,
            )

        dm.save(spec)
        phase = spec["phase"]
        if phase == "confirm_commands":
            return self._build_confirm_commands_response(spec)
        elif phase == "elicit_required":
            return self._build_elicit_required_response(spec)
        elif phase == "elicit_optional":
            return self._build_elicit_optional_response(spec)
        elif phase in ("generate", "refine"):
            return self._build_post_generate_response(spec)
        else:
            return self._build_confirm_commands_response(spec)

    def cancel(self, draft_id: str) -> Dict[str, Any]:
        """Delete the draft and return to idle."""
        try:
            from advisor.session_logger import get_session_logger
            import os
            get_session_logger().finalize(
                draft_id, outcome="cancelled",
                user=os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
            )
        except Exception:
            pass
        get_draft_manager().delete(draft_id)
        return {
            "query": draft_id,
            "response": (
                "Planning session cancelled. Your draft has been discarded.\n\n"
                "Start a new plan any time by describing what you want to set up."
            ),
            "query_type": "plan_clarification",
            "routing_agent": "governance_plan_agent",
            "draft_id": None,
            "phase": "done",
            "can_go_back": False,
            "navigation": [],
            "sources": [], "num_sources": 0,
            "retrieval_time": 0.0, "generation_time": 0.0,
            "avg_relevance_score": 0.0, "context_length": 0,
        }

    def save_and_exit(self, draft_id: str) -> Dict[str, Any]:
        """Confirm the draft is saved and exit the Q&A flow."""
        dm = get_draft_manager()
        spec = dm.load(draft_id)
        title = spec.get("title", draft_id) if spec else draft_id
        return {
            "query": draft_id,
            "response": (
                f"Your planning session for **{title}** has been saved.\n\n"
                f"You can pick it up from the **Drafts** section in the sidebar whenever "
                f"you're ready to continue. I'll show you exactly where you left off."
            ),
            "query_type": "plan_clarification",
            "routing_agent": "governance_plan_agent",
            "draft_id": None,   # clear active draft in UI
            "phase": "saved",
            "can_go_back": False,
            "navigation": [],
            "sources": [], "num_sources": 0,
            "retrieval_time": 0.0, "generation_time": 0.0,
            "avg_relevance_score": 0.0, "context_length": 0,
        }

    def resume(self, draft_id: str) -> Dict[str, Any]:
        """Show a summary of where the draft is and offer to continue."""
        dm = get_draft_manager()
        spec = dm.load(draft_id)
        if spec is None:
            return _error_result(draft_id, f"Draft `{draft_id}` not found.")
        return self._build_resume_response(spec)

    def restart_qa(self, draft_id: str) -> Dict[str, Any]:
        """Keep identified commands but clear all answers and restart Q&A."""
        dm = get_draft_manager()
        spec = dm.load(draft_id)
        if spec is None:
            return _error_result(draft_id, f"Draft `{draft_id}` not found.")

        # Clear answers (but keep pre-fills from the original query)
        spec["answers"] = {}
        spec["history_stack"] = []
        spec["summary_of_answers"] = ""
        # Rebuild pre-fills from commands' pre_filled dicts
        for cmd in spec["commands_identified"]:
            if cmd.get("pre_filled"):
                spec["answers"][cmd["action"]] = dict(cmd["pre_filled"])
        # Rebuild pending questions
        spec["pending_questions"] = self._build_pending_questions(
            spec["commands_identified"], spec["answers"], spec["mode"]
        )
        spec["phase"] = "elicit_required"
        spec["phase_label"] = _PHASE_LABELS["elicit_required"]
        dm.save(spec)
        return self._build_elicit_required_response(spec)

    def discard(self, draft_id: str) -> Dict[str, Any]:
        """Permanently delete a draft (same as cancel but used from sidebar)."""
        return self.cancel(draft_id)

    # ------------------------------------------------------------------
    # Phase handlers
    # ------------------------------------------------------------------

    def _handle_confirm_commands(self, spec: Dict, user_response: str) -> Dict[str, Any]:
        """
        Process the user's response to the confirm_commands step.

        Accepted responses:
          - Confirmation ("yes", "looks good", "continue", "generate now", …)
            → advance to elicit_required or directly to generate
          - Addition ("also add X", "include a term for Y", …)
            → re-decompose additions and merge, then re-show confirm_commands
          - Removal ("remove the zone", "don't need the hierarchy", …)
            → remove matching commands, re-show confirm_commands
          - "fill in details" / "details first"
            → advance to elicit_required
          - "generate now" / "skip details"
            → advance directly to generate (plan with TODOs)
        """
        from advisor.llm_client import get_planning_llm
        from advisor.agents.governance_plan_agent import GovernancePlanAgent

        dm = get_draft_manager()
        low = user_response.lower().strip()

        confirm_words = (
            "yes", "ok", "okay", "looks good", "that's right", "correct",
            "continue", "proceed", "sounds good", "perfect", "great",
        )
        generate_now_words = ("generate now", "skip details", "generate", "create plan now")
        detail_words = ("fill in", "details first", "add details", "more details")

        # --- Direct generation (skip field elicitation) ----------------
        if any(w in low for w in generate_now_words):
            dm.push_history(spec)
            spec["phase"] = "generate"
            spec["phase_label"] = _PHASE_LABELS["generate"]
            dm.save(spec)
            return self._generate_plan(spec)

        # --- Advance to field elicitation ------------------------------
        if any(w in low for w in confirm_words + detail_words):
            dm.push_history(spec)
            spec["phase"] = "elicit_required"
            spec["phase_label"] = _PHASE_LABELS["elicit_required"]
            spec["pending_questions"] = self._build_pending_questions(
                spec["commands_identified"], spec["answers"], spec["mode"]
            )
            dm.save(spec)
            return self._build_elicit_required_response(spec)

        # --- Duplicate / correction detection --------------------------
        # Must come before the re-decompose fallback to avoid treating
        # "steps 1 and 2 are duplicated" as a request to add something.
        dedup_signals = ("duplicate", "duplicated", "same step", "repeated", "appears twice")
        if any(w in low for w in dedup_signals):
            from advisor.plan_validator import validate_commands
            fixed, spec["answers"], val_warnings = validate_commands(
                spec["commands_identified"], spec["answers"]
            )
            if len(fixed) < len(spec["commands_identified"]):
                dm.push_history(spec)
                spec["commands_identified"] = fixed
                dm.save(spec)
                return self._build_confirm_commands_response(
                    spec,
                    note="Removed duplicates. Does this look right now?",
                )
            else:
                return self._build_confirm_commands_response(
                    spec,
                    note=(
                        "I checked for duplicates but didn't find any identical steps. "
                        "Could you point out which step number(s) are the problem? "
                        "For example: *\"remove step 2\"*"
                    ),
                )

        correction_signals = (
            "that's wrong", "that is wrong", "incorrect", "not right",
            "shouldn't have", "should not have", "didn't ask", "i didn't ask",
            "that's not", "wrong step",
        )
        if any(w in low for w in correction_signals):
            return self._build_confirm_commands_response(
                spec,
                note=(
                    "Which step is wrong? You can:\n"
                    "- Say **\"remove step N\"** to delete a specific step\n"
                    "- Say **\"remove the [command name]\"** to remove by name\n"
                    "- Describe what should change instead"
                ),
            )

        # --- Removal request -------------------------------------------
        removal_words = ("remove", "don't need", "drop", "delete", "take out", "without",
                         "remove step")
        if any(w in low for w in removal_words):
            updated = self._remove_commands(spec["commands_identified"], user_response)
            if len(updated) < len(spec["commands_identified"]):
                dm.push_history(spec)
                spec["commands_identified"] = updated
                # Purge answers for removed commands
                kept_actions = {c["action"] for c in updated}
                spec["answers"] = {k: v for k, v in spec["answers"].items() if k in kept_actions}
                dm.save(spec)
                return self._build_confirm_commands_response(
                    spec, note="I've removed those steps. Does the updated plan look right?"
                )

        # --- Addition / refinement request ----------------------------
        # Re-decompose the addition with context of what's already in the plan
        llm = get_planning_llm()
        agent = GovernancePlanAgent()
        try:
            new_decomp = agent._decompose_intent(
                user_response,
                spec.get("perspective"),
                llm,
                existing_commands=spec["commands_identified"],
            )
            from advisor.action_catalog import get_action_catalog
            catalog = get_action_catalog()
            new_commands = []
            for c in new_decomp.get("commands", []):
                if not c.get("action"):
                    continue
                pre_filled = dict(c.get("params") or {})
                new_commands.append({
                    "action":       c["action"],
                    "display_name": c.get("display_name", ""),
                    "description":  c.get("description", ""),
                    "rationale":    c.get("rationale", ""),
                    "narrative":    (
                        c.get("narrative", "")
                        or catalog.narrative_template(c["action"])
                    ),
                    "pre_filled":   pre_filled,
                    "placeholders": {},
                })

            # Sub-projects: multiple "Create Project" commands are allowed (different names)
            # For all other actions, skip duplicates
            added = []
            existing_actions = {c["action"] for c in spec["commands_identified"]}
            for cmd in new_commands:
                if cmd["action"] == "Create Project":
                    added.append(cmd)   # always add — each is a distinct named project
                elif cmd["action"] not in existing_actions:
                    added.append(cmd)

            if added:
                for cmd in added:
                    if cmd.get("display_name") and "Display Name" not in cmd["pre_filled"]:
                        cmd["pre_filled"]["Display Name"] = cmd["display_name"]
                    if cmd["pre_filled"]:
                        # Use action+display_name as key to keep sub-projects distinct
                        key = f"{cmd['action']}:{cmd.get('display_name','')}"
                        spec["answers"].setdefault(key, {}).update(cmd["pre_filled"])
                        cmd["_answers_key"] = key   # remember the key for later lookup

                from advisor.plan_validator import validate_commands
                merged_cmds = spec["commands_identified"] + added
                merged_cmds, spec["answers"], val_warnings = validate_commands(
                    merged_cmds, spec["answers"]
                )
                dm.push_history(spec)
                spec["commands_identified"] = merged_cmds
                dm.save(spec)
                note_parts = [f"Added {len(added)} step(s)."]
                if val_warnings:
                    note_parts.append(
                        "Auto-corrected: " + "; ".join(val_warnings)
                    )
                note_parts.append("Does the plan look right now?")
                return self._build_confirm_commands_response(
                    spec, note=" ".join(note_parts)
                )
        except Exception as exc:
            logger.debug(f"_handle_confirm_commands: addition re-decompose failed: {exc}")

        # Fallback — couldn't parse a structural change; prompt the user
        return self._build_confirm_commands_response(
            spec,
            note=(
                "I wasn't sure how to update the plan from that — could you be more specific?\n\n"
                "For example: *\"Add a glossary term for Revenue\"*, *\"Remove the governance zone\"*,\n"
                "or say **\"yes\"** if the steps look right."
            ),
        )

    def _remove_commands(self, commands: List[Dict], request: str) -> List[Dict]:
        """Heuristically drop commands mentioned in a removal request."""
        import re as _re
        low = request.lower()

        # "remove step N" or "remove steps N and M" — by 1-based index
        indices_to_remove: set = set()
        for m in _re.finditer(r'\bstep[s]?\s+(\d+)', low):
            idx = int(m.group(1)) - 1  # convert to 0-based
            if 0 <= idx < len(commands):
                indices_to_remove.add(idx)
        if indices_to_remove:
            result = [c for i, c in enumerate(commands) if i not in indices_to_remove]
            return result if result else commands

        # Keyword match on action name or display name
        result = []
        for cmd in commands:
            action_low = cmd["action"].lower()
            name_low = (cmd.get("display_name") or "").lower()
            keep = True
            for word in action_low.split() + name_low.split():
                if len(word) > 3 and word in low:
                    keep = False
                    break
            if keep:
                result.append(cmd)
        return result if result else commands  # never remove everything

    def _handle_elicit_required(self, spec: Dict, user_response: str) -> Dict[str, Any]:
        dm = get_draft_manager()
        llm_answers = self._parse_answers(
            user_response,
            spec["pending_questions"].get("required", []),
            spec["commands_identified"],
        )
        _merge_answers(spec["answers"], llm_answers)

        # Check which required fields are still missing
        still_missing = self._get_missing_required(spec)

        if still_missing:
            # Some required fields still unanswered — stay in this phase
            spec["pending_questions"]["required"] = still_missing
            spec["summary_of_answers"] = self._build_summary(spec)
            dm.save(spec)
            return self._build_elicit_required_response(spec, partial=True)

        # All required fields collected — advance to optional
        dm.push_history(spec)
        spec["phase"] = "elicit_optional"
        spec["phase_label"] = _PHASE_LABELS["elicit_optional"]
        spec["pending_questions"] = self._build_pending_questions(
            spec["commands_identified"], spec["answers"], spec["mode"]
        )
        spec["summary_of_answers"] = self._build_summary(spec)
        dm.save(spec)
        return self._build_elicit_optional_response(spec)

    def _handle_elicit_optional(self, spec: Dict, user_response: str) -> Dict[str, Any]:
        dm = get_draft_manager()
        low = user_response.lower().strip()

        # Check if user wants to skip optional fields
        if any(w in low for w in ("skip", "none", "no", "continue", "generate", "done", "that's all", "ok")):
            pass  # proceed to generate without merging optionals
        else:
            # Parse which optional fields they want and any values provided
            optional_qs = spec["pending_questions"].get("optional", [])
            if optional_qs:
                llm_answers = self._parse_answers(
                    user_response, optional_qs, spec["commands_identified"]
                )
                _merge_answers(spec["answers"], llm_answers)

        dm.push_history(spec)
        spec["phase"] = "generate"
        spec["phase_label"] = _PHASE_LABELS["generate"]
        spec["summary_of_answers"] = self._build_summary(spec)
        dm.save(spec)
        return self._generate_plan(spec)

    def _generate_plan(self, spec: Dict) -> Dict[str, Any]:
        """Build and save the plan document, then return a post-generate response."""
        from advisor.agents.governance_plan_agent import GovernancePlanAgent
        from advisor.governance_docs import get_doc_manager

        dm_draft = get_draft_manager()
        agent = GovernancePlanAgent()

        # Merge spec answers back into commands for the composer
        commands_with_params = self._merge_answers_into_commands(spec)

        # Generate narrative
        from advisor.llm_client import get_planning_llm
        llm = get_planning_llm()
        goal, requirements, approach = agent._generate_narrative(
            spec["original_query"],
            spec["original_query"],
            spec.get("perspective"),
            commands_with_params,
            llm,
        )

        doc_content = agent._compose_document(
            title=spec["title"],
            purpose=spec["original_query"],
            perspective=spec.get("perspective") or "Anyone",
            goal=goal,
            requirements=requirements,
            approach=approach,
            commands=commands_with_params,
        )

        doc_manager = get_doc_manager()
        doc_id = doc_manager.create(spec["title"], doc_content)

        spec["doc_id"] = doc_id
        spec["phase"] = "refine"
        spec["phase_label"] = _PHASE_LABELS["refine"]
        dm_draft.push_history(spec)
        dm_draft.save(spec)

        try:
            from advisor.metrics_collector import get_metrics_collector
            families = ",".join(sorted({c["action"].split()[0] for c in commands_with_params}))
            get_metrics_collector().record_plan_event(
                doc_id, "created",
                title=spec["title"],
                command_families=families,
                perspective=spec.get("perspective"),
            )
        except Exception:
            pass

        return self._build_post_generate_response(spec, doc_content=doc_content)

    def _handle_post_generate(self, spec: Dict, user_response: str) -> Dict[str, Any]:
        """User has seen the generated plan — check if they want changes."""
        low = user_response.lower().strip()
        dm = get_draft_manager()

        done_signals = (
            "looks good", "that's good", "good", "perfect", "great", "done",
            "ok", "okay", "ready", "execute", "save as template", "template",
        )
        if any(s in low for s in done_signals) and "change" not in low and "edit" not in low:
            # Move to template offer
            dm.push_history(spec)
            spec["phase"] = "template_offer"
            spec["phase_label"] = _PHASE_LABELS["template_offer"]
            dm.save(spec)
            return self._build_template_offer_response(spec)

        # Treat this as a refinement request
        return self._handle_refine(spec, user_response)

    def _handle_refine(self, spec: Dict, user_response: str) -> Dict[str, Any]:
        """Parse a natural-language change request and update the plan document."""
        from advisor.governance_docs import get_doc_manager
        from advisor.llm_client import get_planning_llm

        dm = get_draft_manager()
        doc_id = spec.get("doc_id")
        if not doc_id:
            return _error_result(spec["draft_id"], "No plan document found — please generate the plan first.")

        doc_manager = get_doc_manager()
        current_content = doc_manager.load(doc_id)
        if not current_content:
            return _error_result(spec["draft_id"], f"Plan document `{doc_id}` not found in inbox.")

        low = user_response.lower().strip()
        done_signals = ("looks good", "that's good", "good", "perfect", "great", "done",
                        "ok", "okay", "ready", "no changes", "no more changes")
        if any(s in low for s in done_signals) and "change" not in low and "edit" not in low:
            dm.push_history(spec)
            spec["phase"] = "template_offer"
            spec["phase_label"] = _PHASE_LABELS["template_offer"]
            dm.save(spec)
            return self._build_template_offer_response(spec)

        # Use LLM to apply the change
        llm = get_planning_llm()
        updated_content = self._apply_change(current_content, user_response, llm)

        if updated_content and updated_content != current_content:
            doc_manager.update(doc_id, updated_content)
            spec["phase"] = "refine"
            spec["phase_label"] = _PHASE_LABELS["refine"]
            dm.save(spec)
            nc = len(re.findall(r"^## [^#]", updated_content, re.MULTILINE))
            return _clarification_result(
                spec,
                f"Done — I've updated the plan. Here's the revised version:\n\n"
                f"---\n\n{updated_content}\n\n---\n\n"
                f"Any other changes? Or say **\"looks good\"** to proceed.\n\n"
                f"You can also **open the editor** to make changes directly.",
                can_go_back=True,
                nav=_NAV_FINAL,
                extra={"doc_id": doc_id},
            )
        else:
            return _clarification_result(
                spec,
                "I wasn't able to identify a specific change from that — could you be more specific?\n\n"
                "For example: *\"Change the glossary name to Finance Terminology\"* or "
                "*\"Add a sub-project called Data Quality\"*.\n\n"
                "Or say **\"looks good\"** if you're happy with the plan as-is.",
                can_go_back=True,
                nav=_NAV_FINAL,
                extra={"doc_id": doc_id},
            )

    def _handle_template_offer(self, spec: Dict, user_response: str) -> Dict[str, Any]:
        """User is responding to the template-save offer."""
        dm = get_draft_manager()
        low = user_response.lower().strip()

        decline_words = ("no", "skip", "don't", "nope", "not", "done", "finish")
        if any(w in low for w in decline_words):
            # Done — clean up draft
            dm.delete(spec["draft_id"])
            doc_id = spec.get("doc_id", "")
            return {
                "query": spec["draft_id"],
                "response": (
                    f"Great — your plan `{doc_id}` is saved in your inbox, ready to review and execute.\n\n"
                    f"Open the **Plan Editor** from the sidebar to review, validate, and execute when ready."
                ),
                "query_type": "plan",
                "routing_agent": "governance_plan_agent",
                "draft_id": None,
                "doc_id": doc_id,
                "phase": "done",
                "can_go_back": False,
                "navigation": [],
                "sources": [], "num_sources": 0,
                "retrieval_time": 0.0, "generation_time": 0.0,
                "avg_relevance_score": 0.0, "context_length": 0,
            }

        # Extract a template name from the response
        name_match = re.search(
            r'(?:call(?:ed)?|name(?:d)?|as)\s+["\']?([^"\']+?)["\']?\s*$',
            user_response, re.IGNORECASE
        )
        if name_match:
            template_name = name_match.group(1).strip()
        elif any(w in low for w in ("yes", "sure", "please", "save", "ok")):
            template_name = spec.get("title", "My Plan Template")
        else:
            # Assume the whole response IS the template name
            template_name = user_response.strip().strip('"\'') or spec.get("title", "My Plan Template")

        # Load and save the plan as a template
        doc_id = spec.get("doc_id", "")
        from advisor.governance_docs import get_doc_manager
        plan_content = get_doc_manager().load(doc_id)
        if plan_content:
            get_template_manager().save(template_name, plan_content)
            saved_msg = f"Saved as template **\"{template_name}\"** — available in the Templates section next time."
        else:
            saved_msg = "Couldn't load the plan document to save as template."

        dm.delete(spec["draft_id"])
        return {
            "query": spec["draft_id"],
            "response": (
                f"{saved_msg}\n\n"
                f"Your plan `{doc_id}` is also in your inbox, ready to execute."
            ),
            "query_type": "plan",
            "routing_agent": "governance_plan_agent",
            "draft_id": None,
            "doc_id": doc_id,
            "phase": "done",
            "can_go_back": False,
            "navigation": [],
            "sources": [], "num_sources": 0,
            "retrieval_time": 0.0, "generation_time": 0.0,
            "avg_relevance_score": 0.0, "context_length": 0,
        }

    # ------------------------------------------------------------------
    # Session logging helpers

    def _log_system_response(
        self, draft_id: str, spec: Dict, result: Dict[str, Any]
    ) -> None:
        """Log the system response and finalize session on terminal states."""
        try:
            from advisor.session_logger import get_session_logger
            import os
            sl = get_session_logger()
            response_text = result.get("response", "")
            result_phase  = result.get("phase", "")
            perspective   = spec.get("perspective") or result.get("perspective")

            sl.log_turn(
                draft_id, role="system",
                content=response_text[:2000],   # truncate long plan docs
                phase=result_phase,
                query_type=result.get("query_type"),
                perspective=perspective,
            )

            # Finalize on terminal states
            if result_phase in ("done", "saved", "error"):
                outcome_map = {
                    "done":  "plan_generated" if result.get("doc_id") else "cancelled",
                    "saved": "saved_in_progress",
                    "error": "error",
                }
                sl.finalize(
                    draft_id,
                    outcome=outcome_map.get(result_phase, result_phase),
                    doc_id=result.get("doc_id"),
                    perspective=perspective,
                    user=os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
                    command_families=",".join(sorted({
                        c["action"].split()[1] if len(c["action"].split()) > 1 else c["action"]
                        for c in spec.get("commands_identified", [])
                    })),
                )
        except Exception:
            pass

    # Response builders
    # ------------------------------------------------------------------

    def _build_confirm_commands_response(
        self, spec: Dict, note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Show the proposed command sequence with template-informed field status,
        then ask the user to confirm, extend, or adjust before any field Q&A.
        """
        from advisor.agents.governance_plan_agent import GovernancePlanAgent, _command_order_key
        agent = GovernancePlanAgent()

        commands = sorted(
            spec["commands_identified"],
            key=lambda c: _command_order_key(c["action"]),
        )
        answers = spec["answers"]

        lines: List[str] = []
        if note:
            lines.append(f"{note}\n")
        lines.append(f"### {spec['title']}\n")
        lines.append("Here's what I'll create, in order:\n")

        for i, cmd in enumerate(commands, 1):
            action = cmd["action"]
            # Check action-only key first, then action:display_name key (used for sub-projects)
            answers_key = cmd.get("_answers_key") or action
            filled = answers.get(answers_key) or answers.get(action) or cmd.get("pre_filled") or {}
            dn = filled.get("Display Name") or cmd.get("display_name") or "*(name TBD)*"
            lines.append(f"**{i}. {action}** — {dn}")

            # Show pre-known params (e.g. Parent ID for sub-projects)
            pre_params = {k: v for k, v in filled.items()
                          if k not in ("Display Name",) and v}
            if pre_params:
                lines.append("   ✓ " + ", ".join(f"{k}: *{v}*" for k, v in pre_params.items()))

            # Use template metadata to flag any still-required fields
            template = agent._load_template(action)
            if template:
                needed = []
                for attr in template["attributes"]:
                    name = attr["name"]
                    if name == "Display Name":
                        continue
                    if attr.get("required") and not (filled.get(name) or filled.get(name.lower())):
                        needed.append(f"**{name}**")
                if needed:
                    lines.append(f"   ○ Still needed: {', '.join(needed)}")
            lines.append("")

        lines.append("---\n")
        lines.append("**Does this look right?**\n")
        lines.append(
            "- Say **\"yes\"** or **\"continue\"** to fill in any missing details\n"
            "- Say **\"generate now\"** to create the plan immediately (missing fields become placeholders)\n"
            "- Describe anything to **add**: *\"also create a sub-project for data collection\"*\n"
            "- Describe anything to **remove**: *\"remove the governance zone\"*"
        )

        return _clarification_result(
            spec, "\n".join(lines),
            phase_override="confirm_commands",
            can_go_back=bool(spec.get("history_stack")),
            nav=_NAV_FIRST,
        )

    def _build_elicit_required_response(self, spec: Dict, partial: bool = False) -> Dict[str, Any]:
        required = spec["pending_questions"].get("required", [])
        answers = spec["answers"]
        commands = spec["commands_identified"]
        mode = spec.get("mode", "basic")

        lines = []
        if not partial:
            lines.append(f"### Planning: {spec['title']}\n")
            lines.append("Here's what I've identified from your description:\n")
            for cmd in commands:
                filled = answers.get(cmd["action"], {})
                dn = filled.get("Display Name") or cmd.get("display_name") or "*(name TBD)*"
                lines.append(f"- **{cmd['action']}** — {dn}")
            lines.append("")
            if mode == "advanced":
                lines.append("*(Advanced mode — all template fields will be shown)*\n")

        if required:
            lines.append("**I need a few more details:**\n")
            # Group questions by command
            by_action: Dict[str, List] = {}
            for q in required:
                by_action.setdefault(q["action"], []).append(q)

            for action, qs in by_action.items():
                lines.append(f"**{action}:**")
                for q in qs:
                    hint = f"*(e.g. {', '.join(q['valid_values'][:3])})*" if q.get("valid_values") else ""
                    desc = q.get("description", "")
                    req_mark = "⚠ required" if q.get("required") else "optional"
                    lines.append(f"- **{q['field']}** — {desc} {hint} *({req_mark})*")
                lines.append("")

            lines.append(
                "Please answer each question. You can answer all at once "
                "(e.g. *\"Zone: Data Management, Owner: finance-team\"*). "
                "Say **\"skip\"** for any you want to leave as TODO."
            )
        else:
            lines.append("All required fields are filled in. ✓")

        can_back = bool(spec["history_stack"])
        nav = _NAV_MIDDLE if can_back else _NAV_FIRST
        return _clarification_result(spec, "\n".join(lines), can_go_back=can_back, nav=nav)

    def _build_elicit_optional_response(self, spec: Dict) -> Dict[str, Any]:
        optional = spec["pending_questions"].get("optional", [])
        mode = spec.get("mode", "basic")

        lines = [f"### {spec['title']} — Required fields complete ✓\n"]
        lines.append(self._format_current_state(spec))
        lines.append("")

        if optional:
            lines.append("**Optional fields** (leave any blank to skip):\n")
            by_action: Dict[str, List] = {}
            for q in optional:
                by_action.setdefault(q["action"], []).append(q)
            for action, qs in by_action.items():
                lines.append(f"**{action}:**")
                for q in qs:
                    hint = f"*(e.g. {', '.join(q['valid_values'][:3])})*" if q.get("valid_values") else ""
                    lines.append(f"- **{q['field']}** {hint} — {q.get('description', '')}")
                lines.append("")
            lines.append(
                "Fill in any you'd like to include, or say **\"continue\"** / **\"skip\"** to generate the plan now."
            )
        else:
            lines.append("No optional fields to fill in.")
            lines.append("\nSay **\"continue\"** to generate the plan.")

        return _clarification_result(spec, "\n".join(lines), can_go_back=True, nav=_NAV_MIDDLE)

    def _build_post_generate_response(
        self, spec: Dict, doc_content: Optional[str] = None
    ) -> Dict[str, Any]:
        doc_id = spec.get("doc_id", "")
        if doc_content is None:
            from advisor.governance_docs import get_doc_manager
            doc_content = get_doc_manager().load(doc_id) or ""

        nc = len(re.findall(r"^<!-- Step \d+", doc_content, re.MULTILINE))
        lines = [
            f"I've created your plan: **{spec['title']}**\n",
            f"Saved as `{doc_id}.md` in your inbox ({nc} command{'s' if nc != 1 else ''}).\n",
            "---\n",
            doc_content,
            "\n---\n",
            "**What would you like to do?**\n",
            "- Say what you'd like to change (e.g. *\"Change the project name to X\"*, *\"Add a sub-project for Data Quality\"*)",
            "- Or **open the editor** to make changes directly",
            "- Say **\"looks good\"** when you're happy and ready to proceed",
        ]
        return _clarification_result(
            spec, "\n".join(lines),
            can_go_back=True, nav=_NAV_FINAL,
            extra={"doc_id": doc_id, "query_type_override": "plan"},
        )

    def _build_resume_response(self, spec: Dict) -> Dict[str, Any]:
        from datetime import datetime
        updated = datetime.fromtimestamp(spec.get("updated_at", 0))
        age = _human_age(spec.get("updated_at", 0))

        lines = [
            f"### Resuming: {spec['title']}\n",
            f"*Last updated {age} — {spec['phase_label']}*\n",
            "",
            self._format_current_state(spec),
            "",
            "**What would you like to do?**",
        ]

        phase = spec["phase"]
        can_back = bool(spec["history_stack"])

        if phase in ("elicit_required", "elicit_optional"):
            return _clarification_result(
                spec, "\n".join(lines),
                can_go_back=can_back,
                nav=_NAV_MIDDLE if can_back else _NAV_FIRST,
                extra={"resume_options": ["continue", "restart", "discard"]},
            )
        elif phase in ("generate", "refine"):
            return _clarification_result(
                spec, "\n".join(lines),
                can_go_back=can_back,
                nav=_NAV_FINAL,
                extra={"doc_id": spec.get("doc_id"), "resume_options": ["continue", "discard"]},
            )
        else:
            return self._build_elicit_required_response(spec)

    def _build_template_offer_response(self, spec: Dict) -> Dict[str, Any]:
        doc_id = spec.get("doc_id", "")
        lines = [
            f"Your plan **{spec['title']}** is complete and saved to your inbox as `{doc_id}.md`.\n",
            "---\n",
            "**Would you like to save this as a reusable plan template?**\n",
            "Templates let you start future plans from this same structure — just fill in the specific names and details.\n",
            "- Say **\"yes\"** to save with the current name, or give it a name: *\"Save as Finance Glossary Template\"*",
            "- Say **\"no\"** or **\"skip\"** to finish without saving a template",
        ]
        return _clarification_result(
            spec, "\n".join(lines),
            can_go_back=True, nav=_NAV_FINAL,
        )

    # ------------------------------------------------------------------
    # Q&A helpers
    # ------------------------------------------------------------------

    def _build_pending_questions(
        self,
        commands: List[Dict],
        answers: Dict[str, Dict],
        mode: str,
    ) -> Dict[str, List]:
        """
        Build required and optional question lists from template attributes,
        excluding fields already in answers.
        """
        from advisor.agents.governance_plan_agent import GovernancePlanAgent
        agent = GovernancePlanAgent()

        required = []
        optional = []

        for cmd in commands:
            action = cmd["action"]
            template = agent._load_template(action)
            if not template:
                continue

            filled = answers.get(action, {})

            for attr in template["attributes"]:
                name = attr["name"]
                # Skip if already answered
                if filled.get(name) or filled.get(name.lower()):
                    continue
                # Skip Display Name if pre-filled from command
                if name == "Display Name" and cmd.get("display_name"):
                    continue

                q = {
                    "action":      action,
                    "field":       name,
                    "required":    attr.get("required", False),
                    "type":        attr.get("type", "Simple"),
                    "description": attr.get("description", ""),
                    "valid_values": attr.get("valid_values", []),
                }
                if attr.get("required"):
                    required.append(q)
                elif mode == "advanced":
                    optional.append(q)
                else:
                    # Basic mode: offer a curated set of useful optionals
                    if name.lower() in ("description", "governance zone", "start date",
                                        "end date", "owner", "steward", "department"):
                        optional.append(q)

        return {"required": required, "optional": optional}

    def _get_missing_required(self, spec: Dict) -> List[Dict]:
        """Return required questions whose fields are still unanswered."""
        answers = spec["answers"]
        missing = []
        for q in spec["pending_questions"].get("required", []):
            action = q["action"]
            field = q["field"]
            filled = answers.get(action, {})
            if not filled.get(field) and not filled.get(field.lower()):
                missing.append(q)
        return missing

    def _pre_fill(
        self,
        query: str,
        commands: List[Dict],
        llm,
    ) -> Dict[str, Dict[str, str]]:
        """
        Use the LLM to extract field values from the user's initial query.
        Returns {action: {field: value}}.
        """
        field_list = []
        for cmd in commands:
            from advisor.agents.governance_plan_agent import GovernancePlanAgent
            template = GovernancePlanAgent()._load_template(cmd["action"])
            if template:
                for attr in template["attributes"][:6]:  # top 6 fields only
                    field_list.append(f"  {cmd['action']} → {attr['name']}")

        if not field_list:
            return {}

        prompt = (
            f"Extract any explicitly mentioned field values from this user request.\n"
            f"User request: \"{query}\"\n\n"
            f"Fields to look for:\n" + "\n".join(field_list) + "\n\n"
            f"Return ONLY a JSON object: {{\"Action Name\": {{\"Field Name\": \"extracted value\"}}}}.\n"
            f"Only include fields where the value is clearly stated in the request. "
            f"Do not invent values. If nothing clear, return {{}}.\nJSON:"
        )
        try:
            raw = llm.generate(prompt, temperature=0.0, max_tokens=500)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as exc:
            logger.debug(f"PlanElicitor._pre_fill failed: {exc}")
        return {}

    def _parse_answers(
        self,
        user_response: str,
        questions: List[Dict],
        commands: List[Dict],
    ) -> Dict[str, Dict[str, str]]:
        """
        Map a free-text user response to {action: {field: value}} using the LLM.
        """
        if not questions or not user_response.strip():
            return {}

        q_desc = "\n".join(
            f"  {q['action']} → {q['field']}: {q.get('description', '')}"
            for q in questions
        )

        prompt = (
            f"The user was asked these questions about a governance plan:\n{q_desc}\n\n"
            f"User's answer: \"{user_response}\"\n\n"
            f"Extract values from the user's answer for each question.\n"
            f"Return ONLY a JSON object: {{\"Action Name\": {{\"Field Name\": \"value\"}}}}.\n"
            f"Only include fields the user actually answered. If skipped or unclear, omit.\n"
            f"JSON:"
        )
        from advisor.llm_client import get_planning_llm
        llm = get_planning_llm()
        try:
            raw = llm.generate(prompt, temperature=0.0, max_tokens=600)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as exc:
            logger.debug(f"PlanElicitor._parse_answers failed: {exc}")
        return {}

    def _apply_change(self, doc_content: str, change_request: str, llm) -> str:
        """Use the LLM to apply a natural-language change to a plan document."""
        prompt = (
            f"You are editing a Dr.Egeria governance plan document.\n"
            f"Apply the following change to the document:\n\n"
            f"Change request: \"{change_request}\"\n\n"
            f"Current document:\n```markdown\n{doc_content[:4000]}\n```\n\n"
            f"Return ONLY the complete updated document (no commentary, no code fences).\n"
            f"Preserve all existing structure. Only change what was requested.\n"
            f"Updated document:"
        )
        try:
            updated = llm.generate(prompt, temperature=0.1, max_tokens=4000)
            # Strip accidental code fences
            updated = re.sub(r"^```(?:markdown)?\n?", "", updated.strip())
            updated = re.sub(r"\n?```$", "", updated.strip())
            return updated.strip()
        except Exception as exc:
            logger.warning(f"PlanElicitor._apply_change failed: {exc}")
            return doc_content

    def _merge_answers_into_commands(self, spec: Dict) -> List[Dict]:
        """Build a commands list with params merged from spec answers (for compose_document)."""
        from advisor.agents.governance_plan_agent import GovernancePlanAgent, _command_order_key
        from advisor.action_catalog import get_action_catalog
        agent   = GovernancePlanAgent()
        catalog = get_action_catalog()
        result  = []
        for cmd in spec["commands_identified"]:
            action      = cmd["action"]
            answers_key = cmd.get("_answers_key") or action
            params      = dict(spec["answers"].get(answers_key) or spec["answers"].get(action) or {})
            # Merge pre_filled params (e.g. Parent ID set during decomposition)
            for k, v in (cmd.get("pre_filled") or {}).items():
                params.setdefault(k, v)
            if cmd.get("display_name") and "Display Name" not in params:
                params["Display Name"] = cmd["display_name"]
            template  = agent._load_template(action)
            narrative = (
                cmd.get("narrative")
                or cmd.get("rationale")
                or catalog.narrative_template(action)
            )
            result.append({
                "action":          action,
                "display_name":    cmd.get("display_name", ""),
                "description":     cmd.get("description", ""),
                "narrative":       narrative,
                "spec":            {"rationale": cmd.get("rationale", "")},
                "template_parsed": template,
                "order":           _command_order_key(action),
                "params":          params,
            })
        return sorted(result, key=lambda x: x["order"])

    def _format_current_state(self, spec: Dict) -> str:
        """Compact summary of what's been collected so far."""
        answers = spec["answers"]
        lines = ["**Collected so far:**\n"]
        for cmd in spec["commands_identified"]:
            action = cmd["action"]
            filled = answers.get(action, {})
            dn = filled.get("Display Name") or cmd.get("display_name") or "*(TBD)*"
            check = "✓" if filled else "○"
            detail = ", ".join(f"{k}: {v}" for k, v in filled.items() if k != "Display Name")
            lines.append(f"- {check} **{action}** — {dn}" + (f" ({detail})" if detail else ""))
        return "\n".join(lines)

    def _build_summary(self, spec: Dict) -> str:
        return self._format_current_state(spec)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _merge_answers(target: Dict[str, Dict], source: Dict[str, Dict]) -> None:
    for action, fields in source.items():
        target.setdefault(action, {}).update(fields)


def _clarification_result(
    spec: Dict,
    response_md: str,
    phase_override: Optional[str] = None,
    can_go_back: bool = False,
    nav: Optional[List[str]] = None,
    extra: Optional[Dict] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "query":            spec.get("original_query", ""),
        "response":         response_md,
        "query_type":       "plan_clarification",
        "routing_agent":    "governance_plan_agent",
        "draft_id":         spec["draft_id"],
        "phase":            phase_override or spec.get("phase", "elicit_required"),
        "can_go_back":      can_go_back,
        "navigation":       nav or _NAV_FIRST,
        "sources":          [],
        "num_sources":      0,
        "retrieval_time":   0.0,
        "generation_time":  0.0,
        "avg_relevance_score": 0.0,
        "context_length":   len(response_md),
    }
    if extra:
        result.update(extra)
    return result


def _error_result(query: str, message: str) -> Dict[str, Any]:
    return {
        "query":            query,
        "response":         message,
        "query_type":       "plan_clarification",
        "routing_agent":    "governance_plan_agent",
        "draft_id":         None,
        "phase":            "error",
        "can_go_back":      False,
        "navigation":       [],
        "sources":          [],
        "num_sources":      0,
        "retrieval_time":   0.0,
        "generation_time":  0.0,
        "avg_relevance_score": 0.0,
        "context_length":   len(message),
    }


def _human_age(ts: float) -> str:
    import time
    diff = time.time() - ts
    if diff < 60:
        return "just now"
    elif diff < 3600:
        return f"{int(diff // 60)} minute{'s' if diff >= 120 else ''} ago"
    elif diff < 86400:
        return f"{int(diff // 3600)} hour{'s' if diff >= 7200 else ''} ago"
    else:
        return f"{int(diff // 86400)} day{'s' if diff >= 172800 else ''} ago"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_elicitor: Optional[PlanElicitor] = None


def get_plan_elicitor() -> PlanElicitor:
    global _elicitor
    if _elicitor is None:
        _elicitor = PlanElicitor()
    return _elicitor
