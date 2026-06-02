"""
Admin API routes for Egeria Advisor.

Endpoints:
  GET  /admin                           → admin.html
  GET  /api/admin/status                → collection + repo + system status
  POST /api/admin/collections/{n}/reindex  → start incremental or force re-index
  POST /api/admin/repos/{repo}/pull     → start git pull
  GET  /api/admin/jobs                  → list recent jobs (last 20)
  GET  /api/admin/jobs/{job_id}         → single job status + output
  POST /api/admin/maintenance/{action}  → refresh_perspectives | refresh_specs |
                                          clear_cache | invalidate_index
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from loguru import logger

router = APIRouter()

_STATIC = Path(__file__).parent / "static"
_REPO_ROOT = Path(__file__).parent.parent.parent
_CONFIG = _REPO_ROOT / "config" / "advisor.yaml"
_DATA_DIR = _REPO_ROOT / "data"
_REPOS_DIR = _DATA_DIR / "repos"
_INDEX_DB = _DATA_DIR / "index_state.db"     # written by incremental_indexer
_ADMIN_STATE_DB = _DATA_DIR / "admin_state.db"  # written here + ingest_collections.py

# ---------------------------------------------------------------------------
# Job tracking
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, job_id: str, job_type: str, description: str):
        self.id = job_id
        self.type = job_type
        self.description = description
        self.status = "running"
        self.lines: List[str] = []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.completed_at: Optional[str] = None
        self.error: Optional[str] = None

    def log(self, line: str) -> None:
        self.lines.append(line)

    def finish(self, error: Optional[str] = None) -> None:
        self.status = "failed" if error else "done"
        self.error = error
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "description": self.description,
            "status": self.status, "output": self.lines[-200:],
            "started_at": self.started_at, "completed_at": self.completed_at,
            "error": self.error,
        }


_jobs: Dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _new_job(job_type: str, description: str) -> Job:
    job = Job(str(uuid.uuid4())[:8], job_type, description)
    with _jobs_lock:
        _jobs[job.id] = job
        # Keep only the last 20 jobs
        if len(_jobs) > 20:
            oldest = sorted(_jobs.keys(),
                            key=lambda k: _jobs[k].started_at)[:len(_jobs) - 20]
            for k in oldest:
                del _jobs[k]
    return job


def _run_job(job: Job, cmd: List[str], cwd: Optional[Path] = None,
             collection_name: Optional[str] = None) -> None:
    """Run a subprocess, stream output to the job, mark done/failed."""
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(cwd or _REPO_ROOT),
        )
        for line in proc.stdout:
            job.log(line.rstrip())
        proc.wait()
        if proc.returncode != 0:
            job.finish(error=f"Process exited with code {proc.returncode}")
        else:
            job.finish()
            # Record successful reindex in admin_state.db
            if collection_name and job.type == "reindex":
                record_ingest_time(collection_name, source="admin")
    except Exception as exc:
        job.log(f"ERROR: {exc}")
        job.finish(error=str(exc))


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _pg_config() -> Dict[str, Any]:
    try:
        with open(_CONFIG) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("pgvector", {})
    except Exception:
        return {}


def _pg_conn():
    import psycopg2
    pg = _pg_config()
    return psycopg2.connect(
        host=pg.get("host", "localhost"),
        port=int(pg.get("port", 5442)),
        database=pg.get("database", "egeria_advisor"),
        user=pg.get("user", "egeria_advisor"),
        password=pg.get("password", ""),
    )


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

_TABLE_NAME_MAP = {"pyegeria_drE": "pyegeria_dre"}


def _table(name: str) -> str:
    return _TABLE_NAME_MAP.get(name, name.lower())


def _vector_counts() -> Dict[str, int]:
    """Return {collection_name: vector_count} for all known collections."""
    counts: Dict[str, int] = {}
    try:
        from advisor.collection_config import ALL_COLLECTIONS
        conn = _pg_conn()
        cur = conn.cursor()
        for name in ALL_COLLECTIONS:
            table = _table(name)
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[name] = cur.fetchone()[0]
            except Exception:
                conn.rollback()
                counts[name] = -1
        cur.close()
        conn.close()
    except Exception as exc:
        logger.debug(f"admin: vector count failed — {exc}")
    return counts


def _ensure_admin_state_db() -> None:
    """Create admin_state.db and its table if not present."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_ADMIN_STATE_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_log (
                collection_name TEXT PRIMARY KEY,
                last_ingested   REAL NOT NULL,
                files_processed INTEGER,
                chunks_created  INTEGER,
                source          TEXT
            )
        """)


def record_ingest_time(
    collection_name: str,
    files: int = 0,
    chunks: int = 0,
    source: str = "admin",
) -> None:
    """Write an ingestion completion record to admin_state.db."""
    try:
        _ensure_admin_state_db()
        with sqlite3.connect(_ADMIN_STATE_DB) as conn:
            conn.execute("""
                INSERT INTO ingest_log (collection_name, last_ingested, files_processed, chunks_created, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(collection_name) DO UPDATE SET
                    last_ingested=excluded.last_ingested,
                    files_processed=excluded.files_processed,
                    chunks_created=excluded.chunks_created,
                    source=excluded.source
            """, (collection_name, time.time(), files, chunks, source))
    except Exception as exc:
        logger.debug(f"admin: record_ingest_time failed — {exc}")


def _last_indexed() -> Dict[str, Optional[float]]:
    """
    Return {collection_name: unix_timestamp} using the best available source:
      1. admin_state.db  — written by ingest_collections.py and admin reindex jobs
      2. index_state.db  — written by incremental_indexer
      3. pg_stat_user_tables.last_autoanalyze — PostgreSQL auto-stats proxy
    Returns the most recent timestamp from whichever source has data.
    """
    result: Dict[str, Optional[float]] = {}

    # Source 1: admin_state.db
    if _ADMIN_STATE_DB.exists():
        try:
            with sqlite3.connect(_ADMIN_STATE_DB) as conn:
                for name, ts in conn.execute(
                    "SELECT collection_name, last_ingested FROM ingest_log"
                ).fetchall():
                    result[name] = ts
        except Exception as exc:
            logger.debug(f"admin: admin_state.db read failed — {exc}")

    # Source 2: index_state.db (incremental indexer)
    if _INDEX_DB.exists():
        try:
            with sqlite3.connect(_INDEX_DB) as conn:
                for name, ts in conn.execute(
                    "SELECT collection_name, MAX(last_indexed) FROM file_tracker "
                    "GROUP BY collection_name"
                ).fetchall():
                    if ts and ts > (result.get(name) or 0):
                        result[name] = ts
        except Exception as exc:
            logger.debug(f"admin: index_state.db read failed — {exc}")

    # Source 3: pg_stat_user_tables — use last_autoanalyze as a proxy for
    # when rows were last bulk-inserted (PostgreSQL auto-analyzes after inserts)
    try:
        conn = _pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT relname,
                   GREATEST(last_analyze, last_autoanalyze) AS last_activity
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
              AND GREATEST(last_analyze, last_autoanalyze) IS NOT NULL
        """)
        import calendar
        for relname, last_activity in cur.fetchall():
            # Reverse-map table name to collection name
            col_name = next(
                (k for k, v in _TABLE_NAME_MAP.items() if v == relname), relname
            )
            ts = calendar.timegm(last_activity.timetuple()) if last_activity else None
            if ts and ts > (result.get(col_name) or 0):
                result[col_name] = ts
        cur.close()
        conn.close()
    except Exception as exc:
        logger.debug(f"admin: pg_stat_user_tables read failed — {exc}")

    return result


def _repo_name_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def _repo_status(repo_path: Path) -> Dict[str, Any]:
    if not (repo_path / ".git").exists():
        return {"exists": False, "last_commit": None, "last_commit_msg": None, "last_pull": None}
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%H|%ai|%s"],
            capture_output=True, text=True, timeout=5,
        )
        parts = result.stdout.strip().split("|", 2)
        sha, date, msg = (parts + ["", "", ""])[:3]
        return {"exists": True, "last_commit": sha[:8], "last_commit_date": date, "last_commit_msg": msg[:80]}
    except Exception:
        return {"exists": True, "last_commit": None, "last_commit_msg": None, "last_pull": None}


def _system_health() -> Dict[str, Any]:
    health: Dict[str, Any] = {"pgvector": False, "ollama": False}
    try:
        conn = _pg_conn()
        conn.close()
        health["pgvector"] = True
    except Exception:
        pass
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        health["ollama"] = True
    except Exception:
        pass
    return health


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(_STATIC / "admin.html")


@router.get("/api/admin/status")
async def admin_status() -> Dict[str, Any]:
    from advisor.collection_config import ALL_COLLECTIONS

    counts = _vector_counts()
    indexed = _last_indexed()

    # Deduplicate repos
    repos_seen: Dict[str, Dict] = {}
    collections_out = []
    for name, meta in ALL_COLLECTIONS.items():
        repo_url = meta.source_repo
        repo_name = _repo_name_from_url(repo_url)
        if repo_name not in repos_seen:
            repo_path = _REPOS_DIR / repo_name
            repos_seen[repo_name] = {
                "name": repo_name,
                "url": repo_url,
                "local_path": str(repo_path),
                **_repo_status(repo_path),
            }

        count = counts.get(name, -1)
        last_ts = indexed.get(name)
        now = time.time()
        age_days = (now - last_ts) / 86400 if last_ts else None

        if not meta.enabled:
            badge = "disabled"
        elif count < 0:
            badge = "error"
        elif count == 0:
            badge = "empty"
        elif age_days is not None and age_days > 7:
            badge = "stale"
        else:
            badge = "healthy"

        collections_out.append({
            "name": name,
            "description": meta.description,
            "enabled": meta.enabled,
            "repo": repo_name,
            "vector_count": count,
            "last_indexed_ts": last_ts,
            "age_days": round(age_days, 1) if age_days is not None else None,
            "badge": badge,
            "source_paths": meta.source_paths,
        })

    return {
        "collections": sorted(collections_out, key=lambda c: (not c["enabled"], c["name"])),
        "repos": list(repos_seen.values()),
        "system": _system_health(),
        "jobs_running": sum(1 for j in _jobs.values() if j.status == "running"),
    }


@router.post("/api/admin/collections/{name}/reindex")
async def reindex_collection(name: str, force: bool = False) -> Dict[str, Any]:
    from advisor.collection_config import ALL_COLLECTIONS
    if name not in ALL_COLLECTIONS:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")

    if force:
        desc = f"Force re-index: {name}"
        cmd = [sys.executable, str(_REPO_ROOT / "scripts" / "ingest_collections.py"),
               "--collection", name, "--force"]
    else:
        desc = f"Incremental re-index: {name}"
        cmd = [sys.executable, "-m", "advisor.incremental_indexer", "--collection", name]

    job = _new_job("reindex", desc)
    threading.Thread(target=_run_job, args=(job, cmd), kwargs={"collection_name": name}, daemon=True).start()
    return {"job_id": job.id, "description": desc}


@router.post("/api/admin/repos/{repo}/pull")
async def pull_repo(repo: str) -> Dict[str, Any]:
    repo_path = _REPOS_DIR / repo
    if not (repo_path / ".git").exists():
        raise HTTPException(status_code=404, detail=f"Repository '{repo}' not found at {repo_path}")

    desc = f"git pull: {repo}"
    job = _new_job("git_pull", desc)
    cmd = ["git", "-C", str(repo_path), "pull", "--ff-only"]
    threading.Thread(target=_run_job, args=(job, cmd), daemon=True).start()
    return {"job_id": job.id, "description": desc}


@router.get("/api/admin/jobs")
async def list_jobs() -> Dict[str, Any]:
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.started_at, reverse=True)
    return {"jobs": [j.to_dict() for j in jobs[:20]]}


@router.get("/api/admin/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.post("/api/admin/maintenance/{action}")
async def maintenance_action(action: str) -> Dict[str, Any]:
    if action == "refresh_perspectives":
        from advisor.perspective_manager import invalidate
        invalidate()
        return {"status": "ok", "message": "Perspective cache invalidated — will reload on next request"}

    if action == "refresh_specs":
        from advisor.report_pipeline import get_report_pipeline
        pipe = get_report_pipeline()
        pipe._egeria_specs_tried = False
        threading.Thread(target=pipe._try_refresh_egeria_specs, daemon=True).start()
        return {"status": "ok", "message": "Report spec refresh started in background"}

    if action == "clear_cache":
        try:
            from advisor.query_cache import get_query_cache
            get_query_cache().clear()
            return {"status": "ok", "message": "Query cache cleared"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    if action == "invalidate_index":
        from advisor.report_pipeline import _question_index
        _question_index.invalidate()
        return {"status": "ok", "message": "QuestionSpecIndex invalidated — will rebuild on next search"}

    raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")
