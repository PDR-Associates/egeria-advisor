"""
DocumentManager — lifecycle management for Governance Plan Documents (GPDs).

Folder layout (all paths configurable in advisor.yaml → governance_plans):
  inbox/     — plans awaiting review or execution
  outbox/    — executed plans with outcome sections appended
  archived/  — superseded or cancelled plans

Each document is a markdown file named:
  {YYYYMMDD_HHMMSS}_{slug}.md

where slug is a URL-safe version of the plan title.
"""
from __future__ import annotations

import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_paths() -> Dict[str, Path]:
    """Read governance_plans paths from advisor.yaml, expanding ~."""
    base = Path.home() / "egeria-plans"
    defaults = {
        "inbox":    base / "inbox",
        "outbox":   base / "outbox",
        "archived": base / "archived",
        "versions": base / "versions",
    }
    try:
        cfg_file = Path(__file__).parent.parent / "config" / "advisor.yaml"
        with open(cfg_file) as f:
            cfg = yaml.safe_load(f)
        gp = cfg.get("governance_plans", {})
        base_cfg = Path(gp.get("inbox", str(base / "inbox"))).expanduser().parent
        return {
            "inbox":    Path(gp["inbox"]).expanduser()    if "inbox"    in gp else defaults["inbox"],
            "outbox":   Path(gp["outbox"]).expanduser()   if "outbox"   in gp else defaults["outbox"],
            "archived": Path(gp["archived"]).expanduser() if "archived" in gp else defaults["archived"],
            "versions": Path(gp["versions"]).expanduser() if "versions" in gp else base_cfg / "versions",
        }
    except Exception as exc:
        logger.debug(f"DocumentManager: using default paths — {exc}")
        return defaults


def _slug(title: str) -> str:
    """Convert a plan title to a filesystem-safe slug."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:60].strip("_")


def _doc_id(path: Path) -> str:
    """Return the doc_id (stem) for a given path."""
    return path.stem


# ---------------------------------------------------------------------------
# DocumentManager
# ---------------------------------------------------------------------------

class DocumentManager:
    """Manages Plan Document files across inbox / outbox / archived folders."""

    def __init__(self) -> None:
        self._paths = _load_paths()
        for p in self._paths.values():
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, title: str, content: str) -> str:
        """
        Write a new plan document to inbox/.

        Returns the doc_id (filename stem) for subsequent operations.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        doc_id = f"{ts}_{_slug(title)}"
        path = self._paths["inbox"] / f"{doc_id}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(f"DocumentManager: created {path}")
        return doc_id

    def load(self, doc_id: str) -> Optional[str]:
        """
        Load a plan document by doc_id from any folder.

        Returns the markdown content, or None if not found.
        """
        for folder in self._paths.values():
            path = folder / f"{doc_id}.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        logger.warning(f"DocumentManager: doc_id {doc_id!r} not found")
        return None

    def update(self, doc_id: str, content: str) -> bool:
        """
        Overwrite a plan document in place (inbox only — executed docs are immutable).

        Saves a versioned backup to versions/ before overwriting.
        Returns True on success.
        """
        path = self._paths["inbox"] / f"{doc_id}.md"
        if not path.exists():
            logger.warning(f"DocumentManager.update: {doc_id!r} not in inbox")
            return False
        self._save_version(doc_id, path.read_text(encoding="utf-8"))
        path.write_text(content, encoding="utf-8")
        logger.info(f"DocumentManager: updated {path}")
        return True

    def _save_version(self, doc_id: str, content: str) -> None:
        """Write a timestamped backup of doc_id to versions/."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ver_path = self._paths["versions"] / f"{doc_id}_v{ts}.md"
        try:
            ver_path.write_text(content, encoding="utf-8")
            logger.debug(f"DocumentManager: saved version {ver_path.name}")
        except Exception as exc:
            logger.warning(f"DocumentManager: version save failed: {exc}")

    def list_versions(self, doc_id: str) -> List[Dict[str, str]]:
        """Return version metadata for a given doc_id, newest first."""
        versions_dir = self._paths["versions"]
        entries = []
        for md in sorted(versions_dir.glob(f"{doc_id}_v*.md"), reverse=True):
            entries.append({"version_file": md.name, "path": str(md)})
        return entries

    def move_to_outbox(self, doc_id: str, outcome_content: str) -> bool:
        """
        Append outcome_content to the plan document and move it to outbox/.

        Returns True on success.
        """
        inbox_path = self._paths["inbox"] / f"{doc_id}.md"
        if not inbox_path.exists():
            logger.warning(f"DocumentManager.move_to_outbox: {doc_id!r} not in inbox")
            return False
        original = inbox_path.read_text(encoding="utf-8")
        final = original.rstrip() + "\n\n---\n\n" + outcome_content.strip() + "\n"
        outbox_path = self._paths["outbox"] / f"{doc_id}.md"
        outbox_path.write_text(final, encoding="utf-8")
        inbox_path.unlink()
        logger.info(f"DocumentManager: moved {doc_id} to outbox")
        return True

    def archive(self, doc_id: str) -> bool:
        """Move a document from inbox to archived/."""
        inbox_path = self._paths["inbox"] / f"{doc_id}.md"
        if not inbox_path.exists():
            logger.warning(f"DocumentManager.archive: {doc_id!r} not in inbox")
            return False
        dest = self._paths["archived"] / f"{doc_id}.md"
        inbox_path.rename(dest)
        logger.info(f"DocumentManager: archived {doc_id}")
        return True

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_inbox(self) -> List[Dict[str, str]]:
        """Return metadata for all documents in inbox/, newest first."""
        return self._list_folder("inbox")

    def list_outbox(self) -> List[Dict[str, str]]:
        """Return metadata for all documents in outbox/, newest first."""
        return self._list_folder("outbox")

    def _list_folder(self, folder: str) -> List[Dict[str, str]]:
        folder_path = self._paths[folder]
        entries = []
        for md in sorted(folder_path.glob("*.md"), reverse=True):
            content = md.read_text(encoding="utf-8", errors="replace")
            title = self._extract_title(content)
            status = self._extract_status(content)
            entries.append({
                "doc_id": md.stem,
                "title": title,
                "status": status,
                "folder": folder,
                "path": str(md),
            })
        return entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_title(content: str) -> str:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return "(untitled)"

    @staticmethod
    def _extract_status(content: str) -> str:
        for line in content.splitlines():
            m = re.search(r"\*\*Status:\*\*\s*(\w+)", line)
            if m:
                return m.group(1)
        return "Draft"

    def inbox_path(self) -> Path:
        return self._paths["inbox"]

    def outbox_path(self) -> Path:
        return self._paths["outbox"]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_doc_manager: Optional[DocumentManager] = None


def get_doc_manager() -> DocumentManager:
    global _doc_manager
    if _doc_manager is None:
        _doc_manager = DocumentManager()
    return _doc_manager
