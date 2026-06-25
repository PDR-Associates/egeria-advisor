"""SQLite-backed symbol table for queryable code structure across all ingested collections.

Populated during ingestion alongside pgvector embeddings. Enables direct SQL answers
to structural questions ("what classes does pyegeria have?", "how many methods does
GlossaryManager expose?") without going through vector search.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger


_SCHEMA = """
CREATE TABLE IF NOT EXISTS code_symbols (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    collection     TEXT    NOT NULL,
    file_path      TEXT    NOT NULL,
    language       TEXT    NOT NULL DEFAULT 'python',
    kind           TEXT    NOT NULL,
    name           TEXT    NOT NULL,
    qualified_name TEXT    NOT NULL,
    signature      TEXT    NOT NULL DEFAULT '',
    docstring      TEXT    NOT NULL DEFAULT '',
    parent_class   TEXT    NOT NULL DEFAULT '',
    return_type    TEXT    NOT NULL DEFAULT '',
    start_line     INTEGER NOT NULL DEFAULT 0,
    end_line       INTEGER NOT NULL DEFAULT 0,
    is_private     INTEGER NOT NULL DEFAULT 0,
    is_async       INTEGER NOT NULL DEFAULT 0,
    complexity     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(collection, file_path, qualified_name)
);
CREATE INDEX IF NOT EXISTS idx_cs_collection_kind ON code_symbols(collection, kind);
CREATE INDEX IF NOT EXISTS idx_cs_collection_name ON code_symbols(collection, name);
CREATE INDEX IF NOT EXISTS idx_cs_parent_class    ON code_symbols(collection, parent_class);
"""

_PYTHON_COLLECTIONS = {"pyegeria", "pyegeria_cli", "pyegeria_dre", "pyegeria_drE"}


def _db_path() -> Path:
    from advisor.config import settings
    cache = getattr(settings, "advisor_cache_dir", None)
    if cache:
        p = Path(cache).parent / "code_symbols.db"
    else:
        p = Path("data") / "code_symbols.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class CodeSymbolStore:
    """Stores and queries code symbols extracted during ingestion."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _db_path()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        logger.info(f"CodeSymbolStore ready at {self.db_path}")

    # ── write ──────────────────────────────────────────────────────────────

    def clear_collection(self, collection: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM code_symbols WHERE collection = ?", (collection,))
        logger.info(f"CodeSymbolStore: cleared symbols for '{collection}'")

    def upsert_symbols(self, collection: str, elements: list[Any]) -> int:
        """Accept a list of CodeElement objects (from advisor/data_prep/code_parser.py)."""
        rows = []
        for el in elements:
            qname = f"{el.parent_class}.{el.name}" if el.parent_class else el.name
            rows.append((
                collection,
                str(el.file_path),
                "python",
                el.type,            # class | function | method
                el.name,
                qname,
                el.signature or "",
                (el.docstring or "")[:500],  # cap to keep DB small
                el.parent_class or "",
                el.return_type or "",
                el.line_number,
                el.end_line_number,
                int(el.is_private),
                int(el.is_async),
                el.complexity,
            ))

        if not rows:
            return 0

        sql = """
            INSERT INTO code_symbols
                (collection, file_path, language, kind, name, qualified_name,
                 signature, docstring, parent_class, return_type,
                 start_line, end_line, is_private, is_async, complexity)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(collection, file_path, qualified_name)
            DO UPDATE SET
                kind=excluded.kind, signature=excluded.signature,
                docstring=excluded.docstring, parent_class=excluded.parent_class,
                return_type=excluded.return_type, start_line=excluded.start_line,
                end_line=excluded.end_line, is_private=excluded.is_private,
                is_async=excluded.is_async, complexity=excluded.complexity
        """
        with self._connect() as conn:
            conn.executemany(sql, rows)
        logger.debug(f"CodeSymbolStore: upserted {len(rows)} symbols into '{collection}'")
        return len(rows)

    # ── aggregate queries ──────────────────────────────────────────────────

    def collection_summary(self, collection: str | None = None) -> dict[str, Any]:
        """Per-collection counts of classes / functions / methods / LOC."""
        where = "WHERE collection = ?" if collection else ""
        params: tuple = (collection,) if collection else ()
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT collection, kind, COUNT(*) n, "
                f"SUM(end_line - start_line + 1) loc "
                f"FROM code_symbols {where} "
                f"GROUP BY collection, kind",
                params,
            ).fetchall()

        summary: dict[str, Any] = {}
        for r in rows:
            col = r["collection"]
            if col not in summary:
                summary[col] = {"classes": 0, "functions": 0, "methods": 0, "loc": 0}
            summary[col][r["kind"] + "s"] = r["n"]
            summary[col]["loc"] = summary[col].get("loc", 0) + (r["loc"] or 0)
        return summary

    def count_by_kind(
        self,
        kind: str,
        collection: str | None = None,
        include_private: bool = True,
    ) -> int:
        parts = ["SELECT COUNT(*) FROM code_symbols WHERE kind = ?"]
        params: list = [kind]
        if collection:
            parts.append("AND collection = ?")
            params.append(collection)
        if not include_private:
            parts.append("AND is_private = 0")
        with self._connect() as conn:
            return conn.execute(" ".join(parts), params).fetchone()[0]

    # ── structural queries ─────────────────────────────────────────────────

    def list_classes(
        self,
        collection: str | None = None,
        include_private: bool = False,
    ) -> list[dict]:
        where = ["kind = 'class'"]
        params: list = []
        if collection:
            where.append("collection = ?")
            params.append(collection)
        if not include_private:
            where.append("is_private = 0")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, collection, file_path, start_line, "
                "end_line - start_line + 1 AS loc, docstring "
                "FROM code_symbols "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY name",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def methods_for_class(
        self,
        class_name: str,
        collection: str | None = None,
        include_private: bool = False,
    ) -> list[dict]:
        where = ["kind = 'method'", "parent_class = ?"]
        params: list = [class_name]
        if collection:
            where.append("collection = ?")
            params.append(collection)
        if not include_private:
            where.append("is_private = 0")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, signature, return_type, is_async, complexity, docstring "
                "FROM code_symbols "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY name",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def search_symbols(
        self,
        name_pattern: str,
        collection: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        where = ["name LIKE ?"]
        params: list = [f"%{name_pattern}%"]
        if collection:
            where.append("collection = ?")
            params.append(collection)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT collection, kind, name, qualified_name, signature, "
                "parent_class, start_line, docstring "
                "FROM code_symbols "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY collection, kind, name "
                "LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def most_complex(
        self,
        collection: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        where = ["kind IN ('function','method')"]
        params: list = []
        if collection:
            where.append("collection = ?")
            params.append(collection)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT collection, kind, name, parent_class, complexity, "
                "start_line, end_line - start_line + 1 AS loc "
                "FROM code_symbols "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY complexity DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def largest_classes(
        self,
        collection: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        where = ["kind = 'class'"]
        params: list = []
        if collection:
            where.append("collection = ?")
            params.append(collection)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT collection, name, "
                "end_line - start_line + 1 AS loc, "
                "(SELECT COUNT(*) FROM code_symbols m "
                " WHERE m.parent_class = code_symbols.name "
                " AND m.collection = code_symbols.collection "
                " AND m.kind = 'method') AS method_count "
                "FROM code_symbols "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY method_count DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def file_summary(
        self,
        collection: str,
        file_path: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, COUNT(*) n FROM code_symbols "
                "WHERE collection=? AND file_path=? GROUP BY kind",
                (collection, file_path),
            ).fetchall()
        return {r["kind"] + "s": r["n"] for r in rows}


# ── singleton ──────────────────────────────────────────────────────────────

_store: CodeSymbolStore | None = None


def get_symbol_store() -> CodeSymbolStore:
    global _store
    if _store is None:
        _store = CodeSymbolStore()
    return _store
