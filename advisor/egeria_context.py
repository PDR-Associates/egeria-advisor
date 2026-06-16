"""
egeria_context.py — Best-effort live context from Egeria for plan enrichment.

Used during LGCI plan generation to:
  - Look up Actor profiles for named individuals in role assignments
  - List governance zones (valid values for zone fields)
  - Check whether a named project / glossary already exists

All public methods return None / [] on any error and never raise —
plan generation continues gracefully when Egeria is unreachable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from loguru import logger

_MCP_CONFIG_PATH = "config/mcp_servers.json"

# Egeria property names that hold the human-readable display name, in priority order
_NAME_PROPS = ("name", "displayName", "knownName", "title")


def _display_name(props: dict) -> str:
    for key in _NAME_PROPS:
        v = props.get(key)
        if v:
            return str(v)
    return props.get("qualifiedName", "")


def _parse_element(elem: dict) -> dict:
    """Extract the fields we care about from a raw Egeria element dict."""
    header = elem.get("elementHeader", {})
    props  = elem.get("properties", {})
    return {
        "guid":           header.get("guid", ""),
        "type_name":      header.get("type", {}).get("typeName", ""),
        "qualified_name": props.get("qualifiedName", ""),
        "display_name":   _display_name(props),
    }


class EgeriaContext:
    """
    Lazy, per-request wrapper around pyegeria OMVs clients.

    Instantiate once per plan decomposition call.  Clients are created on
    first use and reused within the same instance.  Zone list is cached for
    the lifetime of the instance (one planning turn).
    """

    def __init__(self, mcp_config_path: str = _MCP_CONFIG_PATH) -> None:
        self._conn: dict | None = None
        self._conn_loaded = False
        self._mcp_config_path = mcp_config_path
        self._actor_mgr  = None
        self._project_mgr = None
        self._gov_officer = None
        self._glossary_mgr = None
        self._zone_cache: list[str] | None = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def _load_connection(self) -> dict | None:
        """Read Egeria connection params — MCP config first, env vars as fallback."""
        # 1. Try MCP server config (same source as ReportPipeline)
        try:
            p = Path(self._mcp_config_path)
            if p.exists():
                cfg = json.loads(p.read_text())
                env = cfg.get("mcpServers", {}).get("pyegeria", {}).get("env", {})
                conn = {
                    "view_server":  env.get("EGERIA_VIEW_SERVER", ""),
                    "platform_url": env.get("EGERIA_VIEW_SERVER_URL", ""),
                    "user_id":      env.get("EGERIA_USER", ""),
                    "user_pwd":     env.get("EGERIA_PASSWORD", ""),
                }
                if all(conn.values()):
                    return conn
        except Exception:
            pass
        # 2. Env vars
        conn = {
            "view_server":  os.environ.get("EGERIA_VIEW_SERVER", ""),
            "platform_url": os.environ.get("EGERIA_VIEW_SERVER_URL", ""),
            "user_id":      os.environ.get("EGERIA_USER", ""),
            "user_pwd":     os.environ.get("EGERIA_PASSWORD", ""),
        }
        return conn if all(conn.values()) else None

    def _get_connection(self) -> dict | None:
        if not self._conn_loaded:
            self._conn = self._load_connection()
            self._conn_loaded = True
            if not self._conn:
                logger.debug("EgeriaContext: no Egeria connection config — running offline")
        return self._conn

    def _make_client(self, cls):
        """Instantiate and authenticate a pyegeria OMVs client. Returns None on failure."""
        conn = self._get_connection()
        if not conn:
            return None
        try:
            client = cls(**conn)
            client.create_egeria_bearer_token(conn["user_id"], conn["user_pwd"])
            return client
        except Exception as exc:
            logger.debug(f"EgeriaContext: client init failed [{cls.__name__}]: {exc}")
            return None

    def _actor_manager(self):
        if self._actor_mgr is None:
            try:
                from pyegeria.omvs.actor_manager import ActorManager
                self._actor_mgr = self._make_client(ActorManager) or False
            except ImportError:
                self._actor_mgr = False
        return self._actor_mgr or None

    def _project_manager(self):
        if self._project_mgr is None:
            try:
                from pyegeria.omvs.project_manager import ProjectManager
                self._project_mgr = self._make_client(ProjectManager) or False
            except ImportError:
                self._project_mgr = False
        return self._project_mgr or None

    def _governance_officer(self):
        if self._gov_officer is None:
            try:
                from pyegeria.omvs.governance_officer import GovernanceOfficer
                self._gov_officer = self._make_client(GovernanceOfficer) or False
            except ImportError:
                self._gov_officer = False
        return self._gov_officer or None

    def _glossary_manager(self):
        if self._glossary_mgr is None:
            try:
                from pyegeria.omvs.glossary_manager import GlossaryManager
                self._glossary_mgr = self._make_client(GlossaryManager) or False
            except ImportError:
                self._glossary_mgr = False
        return self._glossary_mgr or None

    # ── Public API ─────────────────────────────────────────────────────────────

    def find_actor_by_name(self, name: str) -> dict | None:
        """
        Look up an Actor profile by display name.

        Returns {guid, qualified_name, display_name, type_name}
        or None if not found / Egeria unreachable.

        Prefers an exact case-insensitive name match; falls back to the
        first result if no exact match.
        """
        mgr = self._actor_manager()
        if not mgr:
            return None
        try:
            results = mgr.get_actor_profiles_by_name(name, output_format="JSON")
            if not isinstance(results, list) or not results:
                return None
            name_low = name.lower()
            # Exact match first
            for elem in results:
                parsed = _parse_element(elem)
                if parsed["display_name"].lower() == name_low:
                    return parsed
            # Fallback: first result
            return _parse_element(results[0])
        except Exception as exc:
            logger.debug(f"EgeriaContext.find_actor_by_name({name!r}): {exc}")
            return None

    def list_governance_zones(self) -> list[str]:
        """
        Return all governance zone display names as a list of strings.
        Cached for the lifetime of this instance.
        Returns [] if Egeria is unreachable.
        """
        if self._zone_cache is not None:
            return self._zone_cache

        gov = self._governance_officer()
        if not gov:
            self._zone_cache = []
            return []
        try:
            results = gov.find_governance_definitions("*", output_format="JSON")
            if not isinstance(results, list):
                self._zone_cache = []
                return []
            zones = []
            for elem in results:
                if elem.get("elementHeader", {}).get("type", {}).get("typeName") == "GovernanceZone":
                    name = _display_name(elem.get("properties", {}))
                    if name:
                        zones.append(name)
            self._zone_cache = zones
            logger.debug(f"EgeriaContext: found {len(zones)} governance zone(s)")
            return zones
        except Exception as exc:
            logger.debug(f"EgeriaContext.list_governance_zones: {exc}")
            self._zone_cache = []
            return []

    def find_project_by_name(self, name: str) -> dict | None:
        """
        Check whether a project (or campaign / study) with this display name already exists.
        Returns {guid, qualified_name, display_name, type_name} or None.
        """
        mgr = self._project_manager()
        if not mgr:
            return None
        try:
            results = mgr.get_projects_by_name(name, output_format="JSON")
            if not isinstance(results, list) or not results:
                return None
            name_low = name.lower()
            for elem in results:
                parsed = _parse_element(elem)
                if parsed["display_name"].lower() == name_low:
                    return parsed
            return _parse_element(results[0])
        except Exception as exc:
            logger.debug(f"EgeriaContext.find_project_by_name({name!r}): {exc}")
            return None

    def find_glossary_by_name(self, name: str) -> dict | None:
        """
        Check whether a glossary with this display name already exists.
        Returns {guid, qualified_name, display_name, type_name} or None.
        """
        mgr = self._glossary_manager()
        if not mgr:
            return None
        try:
            results = mgr.get_glossaries_by_name(name, output_format="JSON")
            if not isinstance(results, list) or not results:
                return None
            name_low = name.lower()
            for elem in results:
                parsed = _parse_element(elem)
                if parsed["display_name"].lower() == name_low:
                    return parsed
            return _parse_element(results[0])
        except Exception as exc:
            logger.debug(f"EgeriaContext.find_glossary_by_name({name!r}): {exc}")
            return None

    def enrich_entities(self, entities: dict) -> dict:
        """
        Enrich an extracted entities dict with live Egeria context.

        Adds to each role: actor_guid, actor_qualified_name, actor_found.
        Adds to each object: exists_in_egeria, egeria_guid (if found).
        Returns the enriched dict (mutates in place for efficiency).
        """
        # Enrich roles with actor profile data
        for role in entities.get("roles", []):
            person = role.get("person", "")
            if not person:
                continue
            profile = self.find_actor_by_name(person)
            if profile:
                role["actor_guid"]           = profile["guid"]
                role["actor_qualified_name"] = profile["qualified_name"]
                role["actor_found"]          = True
                logger.debug(f"EgeriaContext: resolved actor {person!r} → {profile['guid'][:8]}…")
            else:
                role["actor_found"] = False
                logger.debug(f"EgeriaContext: actor {person!r} not found in Egeria")

        # Existence check for primary objects
        for obj in entities.get("objects", []):
            otype = obj.get("type", "")
            oname = obj.get("name", "")
            if not oname:
                continue
            existing = None
            if otype in ("project", "campaign", "study_project", "personal_project", "sub_project"):
                existing = self.find_project_by_name(oname)
            elif otype == "glossary":
                existing = self.find_glossary_by_name(oname)
            if existing:
                obj["exists_in_egeria"] = True
                obj["egeria_guid"]      = existing["guid"]
                logger.debug(f"EgeriaContext: {otype} {oname!r} already exists (GUID {existing['guid'][:8]}…)")
            else:
                obj["exists_in_egeria"] = False

        return entities
