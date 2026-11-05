"""Download / convert media via yt-dlp (+ Spotify → YouTube matching)."""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from app.jobs import Job, JobStore
from app.spotify import detect_source

ProgressCb = Callable[[dict], None]

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = ROOT / "downloads"
TOOLS_FFMPEG = ROOT / "tools" / "ffmpeg" / "bin"


def _ensure_ffmpeg_on_path() -> None:
    if shutil.which("ffmpeg"):
        return
    if (TOOLS_FFMPEG / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(TOOLS_FFMPEG) + os.pathsep + os.environ.get("PATH", "")


def _safe_filename(name: str, max_len: int = 120) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "download")[:max_len]


def _clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def _build_ydl_opts(
    outtmpl: str,
    fmt: str,
    progress_hook: ProgressCb | None = None,
    section: tuple[float, float] | None = None,
) -> dict:
    opts: dict = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "windowsfilenames": True,
        "restrictfilenames": False,
        "noprogress": True,
    }

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    if fmt == "mp4":
        opts["format"] = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
        opts["merge_output_format"] = "mp4"
    elif fmt == "wav":
        # Prefer lossless / highest-fidelity source, then decode to 24-bit PCM WAV.
        # Keeps native sample rate (no forced downsample). Files can be heavy.
        opts["format"] = (
            "bestaudio[ext=flac]/bestaudio[ext=wav]/bestaudio[acodec~=flac]/"
            "bestaudio[acodec~=alac]/bestaudio[acodec~=pcm]/"
            "bestaudio/best"
        )
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ]
        opts["postprocessor_args"] = {
            "FFmpegExtractAudio": ["-c:a", "pcm_s24le"],
        }
    else:  # mp3
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",  # best VBR / highest quality
            }
        ]

    if section:
        from yt_dlp.utils import download_range_func

        start, end = section
        # Download only this window, then cut on a keyframe so the file matches it.
        opts["download_ranges"] = download_range_func([], [(start, end)])
        opts["force_keyframes_at_cuts"] = True

    return opts


def _zip_files(files: list[Path], zip_path: Path, fmt: str) -> Path:
    # WAVs barely compress — store raw for speed and to avoid extra work.
    compression = zipfile.ZIP_STORED if fmt == "wav" else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(zip_path, "w", compression=compression) as zf:
        for file_path in files:
            zf.write(file_path, arcname=file_path.name)
    return zip_path


def _collect_outputs(folder: Path) -> list[Path]:
    allowed = {".mp3", ".wav", ".mp4", ".m4a", ".webm", ".mkv", ".opus", ".flac"}
    skip = {".jpg", ".jpeg", ".png", ".webp", ".json", ".part", ".ytdl", ".zip"}
    files = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() in skip:
            continue
        if path.suffix.lower() in allowed:
            files.append(path)
    return sorted(files)


def _track_label(track: dict[str, Any]) -> str:
    artists = (track.get("artists") or "").strip()
    title = (track.get("title") or "Track").strip()
    return f"{artists} - {title}".strip(" -") if artists else title


def _download_urls(
    urls: list[str],
    work_dir: Path,
    fmt: str,
    job: Job,
    store: JobStore,
    labels: list[str] | None = None,
    section: tuple[float, float] | None = None,
) -> list[Path]:
    total = max(len(urls), 1)
    store.update(
        job.id,
        total_items=total,
        completed_items=0,
        status="running",
        message="Starting download…",
    )

    outputs_before = set(_collect_outputs(work_dir))

    for index, url in enumerate(urls):
        label = labels[index] if labels and index < len(labels) else url
        store.update(
            job.id,
            current_item=label,
            message=f"Downloading {index + 1}/{total}: {label}",
            progress=(index / total) * 100,
        )

        def hook(d: dict, idx: int = index, tot: int = total) -> None:
            if d.get("status") == "downloading":
                pct = d.get("_percent_str", "0%").strip().replace("%", "")
                try:
                    file_pct = float(pct)
                except ValueError:
                    file_pct = 0.0
                overall = ((idx + file_pct / 100) / tot) * 100
                store.update(
                    job.id,
                    progress=min(overall, 99.0),
                    message=(
                        f"Downloading {idx + 1}/{tot}: "
                        f"{d.get('_percent_str', '')} {d.get('_speed_str', '')}"
                    ).strip(),
                )
            elif d.get("status") == "finished":
                store.update(job.id, message=f"Processing {idx + 1}/{tot}…")

        if section:
            stamp = f"{_clock(section[0])}-{_clock(section[1])}"
            outtmpl = str(work_dir / f"%(title).140B [{stamp}].%(ext)s")
        else:
            outtmpl = str(work_dir / "%(title).180B [%(id)s].%(ext)s")
        opts = _build_ydl_opts(outtmpl, fmt, progress_hook=hook, section=section)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            store.update(job.id, message=f"Skipped item {index + 1}: {exc}")

        store.update(
            job.id,
            completed_items=index + 1,
            progress=((index + 1) / total) * 100,
        )

    outputs_after = _collect_outputs(work_dir)
    new_files = [p for p in outputs_after if p not in outputs_before]
    return new_files or outputs_after


def _job_section(job: Job) -> tuple[float, float] | None:
    if job.start is None or job.end is None:
        return None
    return (float(job.start), float(job.end))


def run_job(job: Job, store: JobStore) -> None:
    _ensure_ffmpeg_on_path()
    work_dir = DOWNLOADS / job.id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        tracks = job.tracks or []
        if tracks:
            source = job.source or detect_source(job.url) if job.url else "media"
            store.update(
                job.id,
                source=source,
                status="running",
                title=job.title or "Selected tracks",
                message=f"Downloading {len(tracks)} selected track(s)…",
            )
            urls = [t["url"] for t in tracks]
            labels = [_track_label(t) for t in tracks]
            archive_stem = _safe_filename(job.title or "demolec-tracks")
            section = _job_section(job)
            files = _download_urls(
                urls, work_dir, job.format, job, store, labels=labels, section=section
            )
        else:
            # Legacy single-URL path (direct single-item downloads).
            from app.resolver import resolve_url

            source = detect_source(job.url)
            store.update(job.id, source=source, status="running", message="Resolving link…")
            collection = resolve_url(job.url)
            store.update(job.id, title=collection.title)
            urls = [t.url for t in collection.tracks]
            labels = [_track_label(t.to_dict()) for t in collection.tracks]
            archive_stem = _safe_filename(collection.title)
            files = _download_urls(urls, work_dir, job.format, job, store, labels=labels)

        if not files:
            raise RuntimeError(
                "Nothing was downloaded. The link may be private, geo-blocked, or unavailable."
            )

        if len(files) == 1:
            result = files[0]
            store.update(
                job.id,
                status="done",
                progress=100,
                message="Ready to download",
                result_path=str(result),
                result_name=result.name,
                completed_items=1,
                total_items=max(job.total_items, 1),
            )
            return

        zip_path = work_dir / f"{archive_stem}.zip"
        _zip_files(files, zip_path, job.format)
        store.update(
            job.id,
            status="done",
            progress=100,
            message=f"Packaged {len(files)} files into a zip",
            result_path=str(zip_path),
            result_name=zip_path.name,
        )
    except Exception as exc:  # noqa: BLE001
        store.update(
            job.id,
            status="error",
            error=str(exc),
            message="Failed",
            progress=0,
        )
