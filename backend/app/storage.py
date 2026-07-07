from __future__ import annotations

import os
import uuid
import shutil
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")
RETENTION_HOURS = float(os.environ.get("RETENTION_HOURS", "24"))


def ensure_dirs():
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(OUTPUTS_DIR, exist_ok=True)


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def job_upload_path(job_id: str, filename: str) -> str:
    safe_name = os.path.basename(filename)
    job_dir = os.path.join(UPLOADS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return os.path.join(job_dir, safe_name)


def job_output_path(job_id: str, mode: str) -> str:
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return os.path.join(job_dir, f"{mode}.step")


def job_preview_path(job_id: str, mode: str) -> str:
    """Lightweight STL of the *converted output*, used only for the in-browser
    3D preview. Lives next to the STEP so job cleanup removes both together."""
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return os.path.join(job_dir, f"{mode}_preview.stl")


def delete_job_files(job_id: str) -> None:
    """Remove a single job's upload + output folders from disk."""
    for base in (UPLOADS_DIR, OUTPUTS_DIR):
        path = os.path.join(base, job_id)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def cleanup_expired():
    """Delete job folders older than RETENTION_HOURS. Called on a background timer."""
    cutoff = time.time() - RETENTION_HOURS * 3600
    for base in (UPLOADS_DIR, OUTPUTS_DIR):
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            path = os.path.join(base, name)
            try:
                if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass
