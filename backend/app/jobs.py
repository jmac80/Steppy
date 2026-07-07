"""
Small SQLite-backed job table + thread-pool worker. Deliberately not
Redis/Celery for v1 -- this is meant to be easy for one person to
self-host and reason about; a handful of concurrent conversions on a home
server is the expected scale. Swapping in Redis/RQ later (like Stepifi
does) is a drop-in upgrade if you outgrow this.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from . import storage
from .pipeline import convert as convert_pipeline

DB_PATH = None
_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def init(db_path: str, max_workers: int = 2):
    global DB_PATH, _executor
    DB_PATH = db_path
    _executor = ThreadPoolExecutor(max_workers=max_workers)
    with _connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                filename TEXT,
                modes TEXT,
                status TEXT,
                created_at REAL,
                updated_at REAL,
                report TEXT,
                error TEXT
            )
        """)
        # migration for pre-existing databases: per-mode output sequence
        # numbers (JSON {mode: n}) so outputs never overwrite each other
        try:
            con.execute("ALTER TABLE jobs ADD COLUMN seqs TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists


@contextmanager
def _connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def create_job(job_id: str, filename: str, modes: list[str]) -> dict:
    """Insert the job and assign each requested mode the next output sequence
    number for this filename+mode combination (so repeated conversions of the
    same file get -F01, -F02, ... instead of overwriting). Returns {mode: n}."""
    with _connect() as con:
        seqs = {}
        for mode in modes:
            row = con.execute(
                "SELECT COUNT(*) FROM jobs WHERE filename = ? AND modes LIKE ?",
                (filename, f'%"{mode}"%'),
            ).fetchone()
            seqs[mode] = int(row[0]) + 1
        con.execute(
            "INSERT INTO jobs (id, filename, modes, seqs, status, created_at, updated_at, report, error) "
            "VALUES (?, ?, ?, ?, 'queued', ?, ?, NULL, NULL)",
            (job_id, filename, json.dumps(modes), json.dumps(seqs), time.time(), time.time()),
        )
    return seqs


def _update(job_id: str, **fields):
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as con:
        con.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def get_job(job_id: str) -> dict | None:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 50) -> list[dict]:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def fail_interrupted() -> None:
    """Called on startup: any job still marked queued/running was killed by a
    restart mid-conversion. Mark it failed so it doesn't sit immortal and
    undeletable in the list, being polled forever."""
    with _connect() as con:
        con.execute(
            "UPDATE jobs SET status='failed', error='interrupted by a server restart', "
            "updated_at=? WHERE status IN ('queued', 'running')",
            (time.time(),),
        )


def delete_expired(retention_hours: float) -> int:
    """Delete finished jobs older than the retention window -- files AND
    database rows together, so no ghost entries with dead download links."""
    cutoff = time.time() - retention_hours * 3600
    with _connect() as con:
        rows = con.execute(
            "SELECT id FROM jobs WHERE created_at < ? AND status IN ('done', 'failed')",
            (cutoff,),
        ).fetchall()
    ids = [r[0] for r in rows]
    for job_id in ids:
        storage.delete_job_files(job_id)
    delete_jobs(ids)
    return len(ids)


def list_job_ids_by_status(statuses: tuple[str, ...]) -> list[str]:
    """Used by clear-all: only ever targets finished jobs (done/failed), never
    a job that's still queued or running, so an in-flight conversion can't
    have its files pulled out from under it."""
    placeholders = ",".join("?" for _ in statuses)
    with _connect() as con:
        rows = con.execute(f"SELECT id FROM jobs WHERE status IN ({placeholders})", statuses).fetchall()
        return [r[0] for r in rows]


def delete_jobs(job_ids: list[str]) -> None:
    if not job_ids:
        return
    placeholders = ",".join("?" for _ in job_ids)
    with _connect() as con:
        con.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)


def submit(job_id: str, input_path: str, modes: list[str], out_paths: dict,
           unit: str, preview_paths: dict | None = None) -> None:
    _update(job_id, status="running")

    def _run():
        try:
            report = convert_pipeline.convert(
                input_path, out_paths, modes, unit=unit, preview_paths=preview_paths
            )
            _update(job_id, status="done", report=json.dumps(report))
        except Exception as exc:
            _update(job_id, status="failed", error=f"{exc}\n{traceback.format_exc()}")

    _executor.submit(_run)
