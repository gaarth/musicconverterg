"""Demolec — personal media converter / downloader API."""

from __future__ import annotations

import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app.downloader import DOWNLOADS, run_job
from app.jobs import store
from app.resolver import resolve_url
from app.spotify import detect_source

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DOWNLOADS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Demolec", version="1.2.0")
executor = ThreadPoolExecutor(max_workers=3)


class ResolveRequest(BaseModel):
    url: HttpUrl


class TrackPayload(BaseModel):
    id: str
    title: str
    artists: str = ""
    url: str
    duration: int | None = None


class CreateJobRequest(BaseModel):
    format: str = Field(pattern="^(mp3|wav|mp4)$")
    url: HttpUrl | None = None
    title: str = ""
    source: str = ""
    tracks: list[TrackPayload] = Field(default_factory=list)
    start: float | None = None
    end: float | None = None


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "demolec"}


@app.post("/api/resolve")
def resolve_playlist(body: ResolveRequest) -> dict[str, Any]:
    url = str(body.url).strip()
    try:
        detect_source(url)
        collection = resolve_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return collection.to_dict()


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"jobs": [job.to_dict() for job in store.list()]}


@app.delete("/api/jobs")
def clear_jobs() -> dict:
    cleared = store.clear_finished()
    root = DOWNLOADS.resolve()
    for job_id in cleared:
        folder = (DOWNLOADS / job_id).resolve()
        if folder.is_dir() and folder.is_relative_to(root):
            shutil.rmtree(folder, ignore_errors=True)
    return {"cleared": len(cleared), "jobs": [job.to_dict() for job in store.list()]}


@app.post("/api/jobs")
async def create_job(body: CreateJobRequest) -> dict:
    tracks = [t.model_dump() for t in body.tracks]
    url = str(body.url).strip() if body.url else ""

    if not tracks and not url:
        raise HTTPException(
            status_code=400,
            detail="Provide a URL or at least one selected track.",
        )

    has_start = body.start is not None
    has_end = body.end is not None
    if has_start != has_end:
        raise HTTPException(status_code=400, detail="Set both a start and an end time.")
    if has_start and has_end:
        if body.start < 0 or body.end <= body.start:
            raise HTTPException(
                status_code=400,
                detail="End time has to be after the start time.",
            )
        if body.end - body.start < 1:
            raise HTTPException(status_code=400, detail="Pick at least 1 second.")

    if tracks:
        for track in tracks:
            if not track.get("url"):
                raise HTTPException(status_code=400, detail="Each track needs a url.")
        source = body.source or "media"
        title = body.title or "Selected tracks"
    else:
        try:
            source = detect_source(url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        title = body.title

    job = store.create(
        url=url,
        fmt=body.format,
        source=source,
        title=title,
        tracks=tracks,
        start=body.start,
        end=body.end,
    )
    loop = asyncio.get_running_loop()
    loop.run_in_executor(executor, run_job, job, store)
    return job.to_dict()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.result_path:
        raise HTTPException(status_code=409, detail="Download not ready")

    path = Path(job.result_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    media = "application/octet-stream"
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        media = "audio/mpeg"
    elif suffix == ".wav":
        media = "audio/wav"
    elif suffix == ".mp4":
        media = "video/mp4"
    elif suffix == ".zip":
        media = "application/zip"

    return FileResponse(
        path,
        media_type=media,
        filename=job.result_name or path.name,
    )


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
