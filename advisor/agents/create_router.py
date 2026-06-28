"""
CreateRouter — classifies a 'create' intent query as plan, report_spec, or ambiguous.
"""
from __future__ import annotations
import re
from typing import Optional


_PLAN_SIGNALS = re.compile(
    r'\b(?:plan|governance|polic|zone|steward|appoint|assign|workflow|certif|survey|project|campaign|task|actor|role|team|community)\b',
    re.IGNORECASE,
)
_SPEC_SIGNALS = re.compile(
    r'\b(?:report|spec|show|list|find|display|glossar|asset|collection|term|categor|data.class|data.field|schema|database|project)\b',
    re.IGNORECASE,
)

# Ambiguous words present in both (project, community etc.) — break ties by order
_AMBIGUOUS = {'project', 'community'}


def route_create(query: str) -> str:
    """Return 'plan', 'report_spec', or 'ambiguous'."""
    plan_hits = set(m.group().lower() for m in _PLAN_SIGNALS.finditer(query))
    spec_hits = set(m.group().lower() for m in _SPEC_SIGNALS.finditer(query))
    # Remove words that appear in both sets — they don't break ties
    plan_only = plan_hits - spec_hits
    spec_only = spec_hits - plan_hits
    if plan_only and not spec_only:
        return 'plan'
    if spec_only and not plan_only:
        return 'report_spec'
    if plan_only and spec_only:
        # more plan-only signals wins
        return 'plan' if len(plan_only) >= len(spec_only) else 'report_spec'
    return 'ambiguous'
