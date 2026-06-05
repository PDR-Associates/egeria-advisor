"""
plan_validator.py — Deterministic post-processing rules for plan command lists.

Applied after LLM-based intent decomposition to catch and correct structural
errors before showing the confirm_commands step to the user.

Rules applied (in order):
  1. Remove superseded commands   — e.g. "Link Project Hierarchy" is replaced by
                                    "Create Project" with Parent ID set
  2. Ensure required containers   — e.g. Create Glossary must exist before any
                                    Create Glossary Term
  3. Ensure role before appointment — Create Person Role must precede
                                      Link Person Role Appointment
  4. Sort by dependency order      — topological sort using catalog priorities

validate_commands(commands, answers) → (fixed_commands, answers, warnings)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from advisor.action_catalog import get_action_catalog


# ── Public entry point ────────────────────────────────────────────────────────

def validate_commands(
    commands: List[Dict[str, Any]],
    answers: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str]]:
    """
    Apply all validation rules to a command list.

    Returns:
        (fixed_commands, updated_answers, warnings)

    warnings is a list of human-readable messages describing changes made.
    The caller can surface these in the confirm_commands response.
    """
    if answers is None:
        answers = {}

    warnings: List[str] = []

    commands, answers, w = _remove_superseded(commands, answers)
    warnings.extend(w)

    commands, answers, w = _ensure_containers(commands, answers)
    warnings.extend(w)

    commands, w = _ensure_role_before_appointment(commands)
    warnings.extend(w)

    commands = _sort_by_priority(commands)

    logger.debug(
        f"plan_validator: {len(commands)} commands after validation; "
        f"{len(warnings)} warnings: {warnings}"
    )
    return commands, answers, warnings


# ── Rule 1: Remove superseded commands ───────────────────────────────────────

def _remove_superseded(
    commands: List[Dict], answers: Dict
) -> Tuple[List[Dict], Dict, List[str]]:
    """
    Remove any command that is superseded by another command already present.

    Key case: "Link Project Hierarchy" — the catalog says it is superseded by
    "Create Project" with Parent ID. If Create Project commands with parent
    params exist, remove any Link Project Hierarchy commands entirely.
    If Link Project Hierarchy commands exist WITHOUT a corresponding Create
    Project, convert them to Create Project commands.
    """
    catalog = get_action_catalog()
    warnings: List[str] = []
    result = []

    actions_present = {c["action"] for c in commands}

    for cmd in commands:
        name = cmd["action"]
        replacer = catalog.is_superseded_by(name)
        if replacer and replacer in actions_present:
            warnings.append(
                f"Removed '{name}' — it is handled by '{replacer}' with parent params."
            )
            continue

        # Special case: Link Project Hierarchy with no Create Project → convert
        if name == "Link Project Hierarchy" and "Create Project" not in actions_present:
            parent = (
                cmd.get("pre_filled", {}).get("Parent Project")
                or answers.get(name, {}).get("Parent Project")
                or ""
            )
            child = (
                cmd.get("pre_filled", {}).get("Child Project")
                or answers.get(name, {}).get("Child Project")
                or cmd.get("display_name", "")
            )
            new_cmd = {
                "action":       "Create Project",
                "display_name": child,
                "description":  cmd.get("description", ""),
                "rationale":    cmd.get("rationale", ""),
                "narrative":    cmd.get("narrative", ""),
                "pre_filled": {
                    "Display Name": child,
                    "Parent ID": parent,
                    "Parent Relationship Type Name": "ProjectHierarchy",
                },
                "placeholders": {},
            }
            if child:
                answers.setdefault(f"Create Project:{child}", {}).update(new_cmd["pre_filled"])
                new_cmd["_answers_key"] = f"Create Project:{child}"
            result.append(new_cmd)
            warnings.append(
                f"Converted 'Link Project Hierarchy' → 'Create Project' "
                f"with Parent ID='{parent}' (sub-project pattern)."
            )
            continue

        result.append(cmd)

    return result, answers, warnings


# ── Rule 2: Ensure required containers ───────────────────────────────────────

def _ensure_containers(
    commands: List[Dict], answers: Dict
) -> Tuple[List[Dict], Dict, List[str]]:
    """
    For every command that requires a container, ensure that container command
    is present. If missing, prepend a placeholder Create command for it.

    Example: if Create Glossary Term exists but no Create Glossary, insert one.
    """
    catalog = get_action_catalog()
    warnings: List[str] = []
    actions_present = {c["action"] for c in commands}
    to_prepend: List[Dict] = []

    for cmd in commands:
        required = catalog.requires(cmd["action"])
        for req_action in required:
            if req_action not in actions_present and req_action not in {
                c["action"] for c in to_prepend
            }:
                placeholder = {
                    "action":       req_action,
                    "display_name": "",
                    "description":  f"Required before {cmd['action']}",
                    "rationale":    f"Must be created before {cmd['action']}",
                    "narrative":    catalog.narrative_template(req_action),
                    "pre_filled":   {},
                    "placeholders": {},
                }
                to_prepend.append(placeholder)
                warnings.append(
                    f"Added '{req_action}' — required before '{cmd['action']}'."
                )

    return to_prepend + commands, answers, warnings


# ── Rule 3: Ensure role before appointment ───────────────────────────────────

def _ensure_role_before_appointment(
    commands: List[Dict],
) -> Tuple[List[Dict], List[str]]:
    """
    Create Person Role must appear before Link Person Role Appointment.
    This is handled by the sort step, but explicitly verified here.
    """
    warnings: List[str] = []
    actions = [c["action"] for c in commands]
    if (
        "Link Person Role Appointment" in actions
        and "Create Person Role" not in actions
    ):
        # Insert a placeholder Create Person Role
        idx = next(i for i, c in enumerate(commands) if c["action"] == "Link Person Role Appointment")
        placeholder = {
            "action":       "Create Person Role",
            "display_name": "",
            "description":  "Role definition required before appointment",
            "rationale":    "A role must be defined before a person can be appointed to it",
            "narrative":    get_action_catalog().narrative_template("Create Person Role"),
            "pre_filled":   {},
            "placeholders": {},
        }
        commands = commands[:idx] + [placeholder] + commands[idx:]
        warnings.append(
            "Added 'Create Person Role' — required before 'Link Person Role Appointment'."
        )
    return commands, warnings


# ── Rule 4: Sort by dependency order ─────────────────────────────────────────

def _sort_by_priority(commands: List[Dict]) -> List[Dict]:
    """
    Sort commands by catalog ordering_priority, preserving relative order
    within the same priority group (stable sort).
    """
    catalog = get_action_catalog()
    return sorted(commands, key=lambda c: catalog.ordering_priority(c["action"]))
