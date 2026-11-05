"""Resolve Spotify / SoundCloud / YouTube links into selectable track lists."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import unquote, urlparse

import yt_dlp

from app.spotify import detect_source, resolve_spotify


@dataclass
class ResolvedTrack:
    id: str
    title: str
    artists: str
    url: str
    duration: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedCollection:
    source: str
    kind: str
    title: str
    tracks: list[ResolvedTrack]
    is_playlist: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "is_playlist": self.is_playlist,
            "track_count": len(self.tracks),
            "tracks": [t.to_dict() for t in self.tracks],
        }


def _format_duration(seconds: int | None) -> int | None:
    if seconds is None:
        return None
    try:
        value = int(float(seconds))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _prettify_slug(slug: str) -> str:
    text = unquote(slug or "").replace("_", " ").replace("-", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _from_soundcloud_url(url: str) -> tuple[str, str]:
    """Best-effort title/artist from https://soundcloud.com/{artist}/{track}."""
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] not in {"sets", "you", "discover", "pages"}:
        if parts[1] == "sets":
            return "", _prettify_slug(parts[0])
        return _prettify_slug(parts[1]), _prettify_slug(parts[0])
    return "", ""


def _entry_artists(entry: dict[str, Any], fallback_url: str = "") -> str:
    artists = entry.get("artists")
    if isinstance(artists, list):
        names = []
        for item in artists:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
            elif isinstance(item, str) and item.strip():
                names.append(item.strip())
        if names:
            return ", ".join(names)

    for key in ("artist", "uploader", "channel", "creator", "album_artist", "uploader_id"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if fallback_url and "soundcloud.com" in fallback_url:
        _, artist = _from_soundcloud_url(fallback_url)
        return artist
    return ""


def _entry_title(entry: dict[str, Any], index: int, fallback_url: str = "") -> str:
    for key in ("title", "track", "alt_title", "fulltitle", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if fallback_url and "soundcloud.com" in fallback_url:
        title, _ = _from_soundcloud_url(fallback_url)
        if title:
            return title

    return f"Track {index + 1}"


def _entry_url(entry: dict[str, Any]) -> str | None:
    # Prefer stable webpage URLs over temporary stream/CDN links.
    for key in ("webpage_url", "original_url", "url"):
        value = entry.get(key)
        if not isinstance(value, str) or not value.startswith("http"):
            continue
        host = urlparse(value).netloc.lower()
        if "media-streaming.soundcloud" in host or value.endswith(".m3u8"):
            continue
        return value

    entry_id = entry.get("id")
    ie_key = (entry.get("ie_key") or entry.get("extractor_key") or "").lower()
    if entry_id and "soundcloud" in ie_key:
        return f"https://api.soundcloud.com/tracks/{entry_id}"
    return None


def _resolve_spotify(url: str) -> ResolvedCollection:
    collection = resolve_spotify(url)
    tracks = [
        ResolvedTrack(
            id=str(index),
            title=track.title,
            artists=track.artists,
            url=f"ytsearch1:{track.search_query}",
        )
        for index, track in enumerate(collection.tracks)
    ]
    is_playlist = collection.kind in {"playlist", "album"} or len(tracks) > 1
    return ResolvedCollection(
        source="spotify",
        kind=collection.kind,
        title=collection.name,
        tracks=tracks,
        is_playlist=is_playlist,
    )


def _resolve_ytdlp(url: str, source: str) -> ResolvedCollection:
    # SoundCloud flat extraction strips title/uploader — use full metadata there.
    extract_flat: bool | str = False if source == "soundcloud" else "in_playlist"
    probe_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": extract_flat,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("Could not resolve that link.")

    title = info.get("title") or source
    entries = info.get("entries")

    if entries is None:
        track_url = (
            info.get("webpage_url")
            or info.get("original_url")
            or url
        )
        track = ResolvedTrack(
            id=str(info.get("id") or "0"),
            title=_entry_title(info, 0, track_url),
            artists=_entry_artists(info, track_url),
            url=track_url,
            duration=_format_duration(info.get("duration")),
        )
        return ResolvedCollection(
            source=source,
            kind="track",
            title=title,
            tracks=[track],
            is_playlist=False,
        )

    tracks: list[ResolvedTrack] = []
    missing_meta = 0
    for index, entry in enumerate(entries):
        if not entry:
            continue
        track_url = _entry_url(entry)
        if not track_url:
            continue

        track_title = _entry_title(entry, index, track_url)
        artists = _entry_artists(entry, track_url)
        if track_title.startswith("Track ") or not artists:
            missing_meta += 1

        tracks.append(
            ResolvedTrack(
                id=str(entry.get("id") or index),
                title=track_title,
                artists=artists,
                url=track_url,
                duration=_format_duration(entry.get("duration")),
            )
        )

    # YouTube/others sometimes return bare URLs in flat mode — enrich if needed.
    if tracks and missing_meta >= max(1, len(tracks) // 2) and extract_flat:
        return _resolve_ytdlp_full(url, source)

    if not tracks:
        raise RuntimeError(
            "No tracks found in this playlist. It may be private or empty."
        )

    kind = "playlist"
    if source == "soundcloud":
        kind = "set" if len(tracks) > 1 else "track"

    return ResolvedCollection(
        source=source,
        kind=kind,
        title=title,
        tracks=tracks,
        is_playlist=len(tracks) > 1,
    )


def _resolve_ytdlp_full(url: str, source: str) -> ResolvedCollection:
    """Second-pass resolve with full metadata when flat mode lacks titles."""
    probe_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info or not info.get("entries"):
        raise RuntimeError("Could not resolve track names for that playlist.")

    title = info.get("title") or source
    tracks: list[ResolvedTrack] = []
    for index, entry in enumerate(info.get("entries") or []):
        if not entry:
            continue
        track_url = _entry_url(entry)
        if not track_url:
            continue
        tracks.append(
            ResolvedTrack(
                id=str(entry.get("id") or index),
                title=_entry_title(entry, index, track_url),
                artists=_entry_artists(entry, track_url),
                url=track_url,
                duration=_format_duration(entry.get("duration")),
            )
        )

    if not tracks:
        raise RuntimeError(
            "No tracks found in this playlist. It may be private or empty."
        )

    return ResolvedCollection(
        source=source,
        kind="set" if source == "soundcloud" else "playlist",
        title=title,
        tracks=tracks,
        is_playlist=len(tracks) > 1,
    )


def resolve_url(url: str) -> ResolvedCollection:
    source = detect_source(url)
    if source == "spotify":
        return _resolve_spotify(url)
    return _resolve_ytdlp(url, source)
