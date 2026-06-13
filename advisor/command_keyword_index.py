"""
CommandKeywordIndex — maps natural-language phrases to Dr.Egeria command names.

Sources (in decreasing confidence):
  1. Action catalog aliases → confidence 0.95 (explicitly curated)
  2. Catalog command names (normalised) → confidence 0.90
  3. Template filesystem names (uncatalogued) → confidence 0.75
  4. Partial substring match against any of the above → confidence 0.55

Usage:
    idx = get_command_keyword_index()
    match = idx.lookup("blueprint")
    if match and match.confidence >= 0.7:
        command_name = match.command   # "Create Solution Blueprint"
    elif match:
        suggestion = f"Did you mean {match.command}?"
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from loguru import logger


@dataclass
class CommandMatch:
    command: str        # Canonical Dr.Egeria command name
    family: str         # Template family (e.g. "Solution Architect")
    confidence: float   # 0.0–1.0
    source: str         # "alias" | "catalog_name" | "template_name" | "partial"


class CommandKeywordIndex:
    """
    Searchable index of all known Dr.Egeria commands and their natural-language aliases.
    Built lazily from the action catalog and the template filesystem.
    """

    def __init__(self) -> None:
        self._entries: List[Dict] = []   # [{command, family, terms: [str], source_tier}]
        self._built = False

    # ── Build ──────────────────────────────────────────────────────────────────

    def _ensure_built(self) -> None:
        if self._built:
            return
        self._entries = []
        self._load_catalog()
        self._load_templates()
        self._built = True
        logger.debug(f"CommandKeywordIndex: {len(self._entries)} entries loaded")

    def _load_catalog(self) -> None:
        catalog_path = Path(__file__).parent.parent / "config" / "dr_egeria_actions.yaml"
        try:
            with open(catalog_path) as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning(f"CommandKeywordIndex: could not load catalog: {exc}")
            return

        for action in data.get("actions", []):
            name = action.get("name", "")
            family = action.get("family", "")
            if not name:
                continue
            aliases = action.get("aliases", [])
            # Include normalized command name as an alias too
            self._entries.append({
                "command": name,
                "family": family,
                "terms": [a.lower() for a in aliases],
                "name_normalized": self._normalize(name),
                "source_tier": "catalog",
            })

    def _load_templates(self) -> None:
        """Scan template filesystem for command names not already in the catalog."""
        catalogued = {e["command"].lower() for e in self._entries}

        template_root = self._find_template_root()
        if not template_root:
            return

        for md_file in template_root.rglob("*.md"):
            # Decode filename: "Create_Solution_Blueprint.md" → "Create Solution Blueprint"
            command_name = md_file.stem.replace("_", " ")
            if command_name.lower() in catalogued:
                continue
            # Family is the parent folder name
            family = md_file.parent.name
            # Skip the basic/advanced level folder
            if family in ("basic", "advanced"):
                family = md_file.parent.parent.name

            self._entries.append({
                "command": command_name,
                "family": family,
                "terms": [],
                "name_normalized": self._normalize(command_name),
                "source_tier": "template",
            })
            catalogued.add(command_name.lower())

    def _find_template_root(self) -> Optional[Path]:
        """Find the Dr-Egeria-Templates directory."""
        candidates = [
            # Data repos clone
            Path(__file__).parent.parent / "data" / "repos" / "egeria-workspaces" /
            "exchange-quickstart" / "Templates" / "Dr-Egeria-Templates",
            # Workspace filesystem
            Path("/Users/dwolfson/localGit/egeria-v6/egeria-workspaces-fs") /
            "exchange-quickstart" / "Templates" / "Dr-Egeria-Templates",
        ]
        # Try pyegeria config
        try:
            import pyegeria.core.config as cfg
            root = Path(cfg.get_app_config().Environment.pyegeria_root)
            candidates.insert(0, root / "Templates" / "Dr-Egeria-Templates")
            candidates.insert(0, root / "templates")
        except Exception:
            pass

        for path in candidates:
            if path.exists():
                # Prefer the basic/ subtree to avoid duplicates
                basic = path / "basic"
                return basic if basic.exists() else path
        return None

    # ── Lookup ─────────────────────────────────────────────────────────────────

    def lookup(self, phrase: str) -> Optional[CommandMatch]:
        """
        Return the best CommandMatch for the given phrase, or None if nothing
        scores above 0.50.

        Scoring tiers:
          0.95 — exact alias match (catalog entry)
          0.90 — exact normalized command name match
          0.75 — exact normalized match against template-only entry
          0.55 — partial: phrase is a substring of an alias or command name,
                          or an alias is a substring of phrase
        """
        self._ensure_built()
        phrase_n = self._normalize(phrase)
        if not phrase_n:
            return None

        best: Optional[CommandMatch] = None
        best_score = 0.0

        for entry in self._entries:
            is_catalog = entry["source_tier"] == "catalog"

            # Tier 1: exact alias match
            for term in entry["terms"]:
                if phrase_n == term:
                    score = 0.95
                    if score > best_score:
                        best_score = score
                        best = CommandMatch(entry["command"], entry["family"], score, "alias")

            # Tier 2/3: exact normalized command name
            if phrase_n == entry["name_normalized"]:
                score = 0.90 if is_catalog else 0.75
                if score > best_score:
                    best_score = score
                    src = "catalog_name" if is_catalog else "template_name"
                    best = CommandMatch(entry["command"], entry["family"], score, src)

            # Tier 4: partial match (only if nothing better found yet)
            if best_score < 0.60:
                # phrase is contained in alias or name
                for term in entry["terms"] + [entry["name_normalized"]]:
                    if phrase_n in term or term in phrase_n:
                        score = 0.55
                        if score > best_score:
                            best_score = score
                            best = CommandMatch(entry["command"], entry["family"], score, "partial")

        return best if best_score >= 0.50 else None

    def all_commands(self) -> List[Dict]:
        """Return all commands grouped for the /api/actions endpoint."""
        self._ensure_built()
        seen: Dict[str, Dict] = {}
        for entry in self._entries:
            key = entry["command"]
            if key not in seen:
                seen[key] = {
                    "name": entry["command"],
                    "family": entry["family"],
                    "aliases": entry["terms"],
                    "in_catalog": entry["source_tier"] == "catalog",
                }
        # Group by family
        groups: Dict[str, List] = {}
        for cmd in seen.values():
            fam = cmd["family"] or "Other"
            groups.setdefault(fam, []).append(cmd)
        # Sort families and commands within each family
        return {fam: sorted(cmds, key=lambda c: c["name"])
                for fam, cmds in sorted(groups.items())}

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(s: str) -> str:
        """Lowercase, collapse spaces, strip punctuation for comparison."""
        s = s.lower().strip()
        s = re.sub(r'[_\-\.]', ' ', s)
        s = re.sub(r'\s+', ' ', s)
        # Remove common leading articles/verbs for matching purposes
        s = re.sub(r'^(?:create|link|add|attach|classify|set)\s+', '', s)
        return s.strip()


# ── Singleton ──────────────────────────────────────────────────────────────────

_index: Optional[CommandKeywordIndex] = None


def get_command_keyword_index() -> CommandKeywordIndex:
    global _index
    if _index is None:
        _index = CommandKeywordIndex()
    return _index
