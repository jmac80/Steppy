from __future__ import annotations

import json
import os
import threading
import time

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from . import storage, jobs

app = FastAPI(title="Steppy", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_MODES = {"faceted"}
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024


def output_display_name(filename: str, mode: str, seq: int) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return f"{stem}-{seq:02d}.step"


@app.on_event("startup")
def _startup():
    storage.ensure_dirs()
    jobs.init(os.path.join(storage.DATA_DIR, "jobs.db"))
    jobs.fail_interrupted()

    def _cleanup_loop():
        while True:
            jobs.delete_expired(storage.RETENTION_HOURS)
            storage.cleanup_expired()
            time.sleep(3600)

    threading.Thread(target=_cleanup_loop, daemon=True).start()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    modes: str = Form("faceted"),
    unit: str = Form("MM"),
):
    requested_modes = [m.strip() for m in modes.split(",") if m.strip()]
    invalid = set(requested_modes) - ALLOWED_MODES
    if invalid:
        raise HTTPException(400, f"unknown mode(s): {sorted(invalid)}")
    if not requested_modes:
        raise HTTPException(400, "at least one mode must be requested")
    if not file.filename.lower().endswith(".stl"):
        raise HTTPException(400, "only .stl uploads are supported right now")

    job_id = storage.new_job_id()
    upload_path = storage.job_upload_path(job_id, file.filename)

    size = 0
    with open(upload_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(upload_path)
                raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)}MB limit")
            f.write(chunk)

    out_paths = {mode: storage.job_output_path(job_id, mode) for mode in requested_modes}
    preview_paths = {mode: storage.job_preview_path(job_id, mode) for mode in requested_modes}

    seqs = jobs.create_job(job_id, file.filename, requested_modes)
    jobs.submit(
        job_id, upload_path, requested_modes, out_paths, unit,
        preview_paths=preview_paths,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "modes": requested_modes,
        "output_names": {m: output_display_name(file.filename, m, seqs.get(m, 1))
                          for m in requested_modes},
    }


@app.get("/api/jobs")
def list_jobs():
    return [_serialize_job(j) for j in jobs.list_jobs()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _serialize_job(job)


@app.get("/api/jobs/{job_id}/download/{mode}")
def download(job_id: str, mode: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    path = storage.job_output_path(job_id, mode)
    if not os.path.exists(path):
        raise HTTPException(404, "output not ready or mode was not requested")
    seqs = json.loads(job.get("seqs") or "{}")
    filename = output_display_name(job["filename"], mode, seqs.get(mode, 1))
    return FileResponse(path, filename=filename, media_type="application/step")


@app.get("/api/jobs/{job_id}/preview/{mode}")
def preview(job_id: str, mode: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    path = storage.job_preview_path(job_id, mode)
    if not os.path.exists(path):
        raise HTTPException(404, "no preview available for this mode")
    return FileResponse(path, media_type="application/octet-stream")


@app.delete("/api/jobs")
def clear_jobs():
    ids = jobs.list_job_ids_by_status(("done", "failed"))
    for job_id in ids:
        storage.delete_job_files(job_id)
    jobs.delete_jobs(ids)
    return {"cleared": len(ids)}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job["status"] not in ("done", "failed"):
        raise HTTPException(409, "job is still queued/running -- can't delete yet")
    storage.delete_job_files(job_id)
    jobs.delete_jobs([job_id])
    return {"deleted": job_id}


def _serialize_job(job: dict) -> dict:
    out = dict(job)
    out["modes"] = json.loads(job["modes"]) if job.get("modes") else []
    out["report"] = json.loads(job["report"]) if job.get("report") else None
    seqs = json.loads(job.get("seqs") or "{}")
    out["output_names"] = {m: output_display_name(job["filename"], m, seqs.get(m, 1))
                            for m in out["modes"]}
    return out
