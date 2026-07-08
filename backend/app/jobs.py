
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
        try:
            con.execute("ALTER TABLE jobs ADD COLUMN seqs TEXT")
        except sqlite3.OperationalError:
            pass


@contextmanager
def _connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def create_job(job_id: str, filename: str, modes: list[str]) -> dict:
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
    with _connect() as con:
        con.execute(
            "UPDATE jobs SET status='failed', error='interrupted by a server restart', "
            "updated_at=? WHERE status IN ('queued', 'running')",
            (time.time(),),
        )


def delete_expired(retention_hours: float) -> int:
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
