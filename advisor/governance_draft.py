"""
DraftManager — lifecycle management for in-progress plan Q&A sessions.

Draft specs are stored as JSON in ~/egeria-plans/drafts/.
Each draft captures the full conversation state so planning sessions
can be paused, resumed, rewound (Back), or abandoned (Start Over).

Draft spec schema:
  draft_id          — unique ID (timestamp + slug)
  title             — plan title (may be provisional)
  phase             — current state machine phase
  phase_label       — human-readable "where you are"
  mode              — "basic" | "advanced"
  perspective       — active user role
  original_query    — verbatim user request that started the plan
  template_name     — name of plan template used as starting point (or null)
  commands_identified — list of {action, display_name, description, rationale, pre_filled}
  answers           — {action: {field: value}} accumulated so far
  pending_questions — {required: [...], optional: [...]}
  doc_id            — set after the plan document is generated (inbox doc_id)
  history_stack     — list of snapshot dicts for Back navigation
  created_at        — Unix timestamp
  updated_at        — Unix timestamp
  summary_of_answers — short markdown recap shown on resume
"""
from __future__ import annotations

import json
import re
import time
import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _drafts_path() -> Path:
    """Return path to the drafts folder, creating it if necessary."""
    base = Path.home() / "egeria-plans"
    default = base / "drafts"
    try:
        cfg_file = Path(__file__).parent.parent / "config" / "advisor.yaml"
        with open(cfg_file) as f:
            cfg = yaml.safe_load(f)
        gp = cfg.get("governance_plans", {})
        p = Path(gp["drafts"]).expanduser() if "drafts" in gp else default
    except Exception:
        p = default
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slug(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:40].strip("_")


# ---------------------------------------------------------------------------
# DraftManager
# ---------------------------------------------------------------------------

class DraftManager:
    """CRUD for plan draft specs."""

    def __init__(self) -> None:
        self._root = _drafts_path()

    def _path(self, draft_id: str) -> Path:
        return self._root / f"{draft_id}.json"

    # ------------------------------------------------------------------
    # Create / Load / Save / Delete
    # ------------------------------------------------------------------

    def create(
        self,
        title: str,
        original_query: str,
        commands_identified: List[Dict],
        pending_questions: Dict,
        pre_filled_answers: Dict,
        mode: str = "basic",
        perspective: Optional[str] = None,
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new draft spec, persist it, and return it."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        draft_id = f"draft_{ts}_{_slug(title)}"
        spec: Dict[str, Any] = {
            "draft_id": draft_id,
            "title": title,
            "phase": "elicit_required",
            "phase_label": "Answering required field questions",
            "mode": mode,
            "perspective": perspective,
            "original_query": original_query,
            "template_name": template_name,
            "commands_identified": commands_identified,
            "answers": pre_filled_answers,
            "pending_questions": pending_questions,
            "doc_id": None,
            "history_stack": [],
            "created_at": time.time(),
            "updated_at": time.time(),
            "summary_of_answers": "",
        }
        self._write(spec)
        return spec

    def load(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Load a draft by ID. Returns None if not found."""
        p = self._path(draft_id)
        if not p.exists():
            logger.warning(f"DraftManager: draft {draft_id!r} not found")
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(f"DraftManager: failed to load {draft_id}: {exc}")
            return None

    def save(self, spec: Dict[str, Any]) -> None:
        """Persist a draft spec (updates updated_at)."""
        spec["updated_at"] = time.time()
        self._write(spec)

    def delete(self, draft_id: str) -> bool:
        """Delete a draft. Returns True if found and deleted."""
        p = self._path(draft_id)
        if p.exists():
            p.unlink()
            logger.info(f"DraftManager: deleted {draft_id}")
            return True
        return False

    def _write(self, spec: Dict[str, Any]) -> None:
        p = self._path(spec["draft_id"])
        p.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # History (Back navigation)
    # ------------------------------------------------------------------

    def push_history(self, spec: Dict[str, Any]) -> None:
        """Snapshot current mutable state onto the history stack before advancing."""
        snapshot = {
            "phase": spec["phase"],
            "phase_label": spec["phase_label"],
            "answers": copy.deepcopy(spec["answers"]),
            "pending_questions": copy.deepcopy(spec["pending_questions"]),
            "summary_of_answers": spec.get("summary_of_answers", ""),
        }
        spec["history_stack"].append(snapshot)

    def pop_history(self, spec: Dict[str, Any]) -> bool:
        """Restore the previous state from the history stack. Returns True if rewound."""
        if not spec["history_stack"]:
            return False
        snapshot = spec["history_stack"].pop()
        spec["phase"] = snapshot["phase"]
        spec["phase_label"] = snapshot["phase_label"]
        spec["answers"] = snapshot["answers"]
        spec["pending_questions"] = snapshot["pending_questions"]
        spec["summary_of_answers"] = snapshot.get("summary_of_answers", "")
        return True

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_drafts(self) -> List[Dict[str, Any]]:
        """Return metadata for all active drafts, newest first."""
        entries = []
        for jf in sorted(self._root.glob("draft_*.json"), reverse=True):
            try:
                spec = json.loads(jf.read_text(encoding="utf-8"))
                entries.append({
                    "draft_id":    spec["draft_id"],
                    "title":       spec.get("title", "(untitled)"),
                    "phase":       spec.get("phase", "unknown"),
                    "phase_label": spec.get("phase_label", ""),
                    "mode":        spec.get("mode", "basic"),
                    "updated_at":  spec.get("updated_at", 0),
                    "created_at":  spec.get("created_at", 0),
                })
            except Exception:
                pass
        return entries


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_dm: Optional[DraftManager] = None


def get_draft_manager() -> DraftManager:
    global _dm
    if _dm is None:
        _dm = DraftManager()
    return _dm
