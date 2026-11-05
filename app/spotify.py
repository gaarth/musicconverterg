"""Resolve Spotify track/album/playlist metadata via public embed pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import requests

SpotifyKind = Literal["track", "album", "playlist"]

_EMBED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class SpotifyTrack:
    title: str
    artists: str

    @property
    def search_query(self) -> str:
        return f"{self.artists} - {self.title}".strip(" -")


@dataclass
class SpotifyCollection:
    kind: SpotifyKind
    name: str
    tracks: list[SpotifyTrack]


_SPOTIFY_RE = re.compile(
    r"(?:https?://)?(?:open\.)?spotify\.com/(?:intl-[a-z]{2}/)?"
    r"(track|album|playlist)/([a-zA-Z0-9]+)",
    re.IGNORECASE,
)


def is_spotify_url(url: str) -> bool:
    return bool(_SPOTIFY_RE.search(url))


def parse_spotify_url(url: str) -> tuple[SpotifyKind, str]:
    match = _SPOTIFY_RE.search(url)
    if not match:
        raise ValueError("Not a valid Spotify track, album, or playlist URL.")
    return match.group(1).lower(), match.group(2)  # type: ignore[return-value]


def _fetch_embed_entity(kind: SpotifyKind, spotify_id: str) -> dict:
    embed_url = f"https://open.spotify.com/embed/{kind}/{spotify_id}"
    response = requests.get(embed_url, headers=_EMBED_HEADERS, timeout=30)
    response.raise_for_status()

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError("Could not parse Spotify embed data.")

    payload = json.loads(match.group(1))
    entity = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("state", {})
        .get("data", {})
        .get("entity")
    )
    if not entity:
        raise RuntimeError("Spotify embed did not include entity metadata.")
    return entity


def _artists_from_entity(entity: dict) -> str:
    artists = entity.get("artists") or []
    if artists:
        return ", ".join(a.get("name", "") for a in artists if a.get("name"))
    subtitle = entity.get("subtitle") or ""
    return subtitle.replace("\xa0", " ").strip()


def resolve_spotify(url: str) -> SpotifyCollection:
    kind, spotify_id = parse_spotify_url(url)
    entity = _fetch_embed_entity(kind, spotify_id)
    name = entity.get("name") or entity.get("title") or "Spotify"

    if kind == "track":
        track = SpotifyTrack(
            title=entity.get("title") or entity.get("name") or "Unknown",
            artists=_artists_from_entity(entity),
        )
        return SpotifyCollection(kind=kind, name=name, tracks=[track])

    tracks: list[SpotifyTrack] = []
    for item in entity.get("trackList") or []:
        title = (item.get("title") or item.get("name") or "").strip()
        artists = (item.get("subtitle") or "").replace("\xa0", " ").strip()
        if not artists:
            nested = item.get("artists") or []
            if isinstance(nested, list):
                artists = ", ".join(
                    a.get("name", "") for a in nested if isinstance(a, dict) and a.get("name")
                )
        if title:
            tracks.append(SpotifyTrack(title=title, artists=artists or "Unknown artist"))

    if not tracks:
        raise RuntimeError(
            "No tracks found in this Spotify link. "
            "Try a public playlist/album, or paste individual track links."
        )

    return SpotifyCollection(kind=kind, name=name, tracks=tracks)


def detect_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "spotify.com" in host:
        return "spotify"
    if "soundcloud.com" in host:
        return "soundcloud"
    if "youtube.com" in host or "youtu.be" in host or "music.youtube.com" in host:
        return "youtube"
    raise ValueError(
        "Unsupported URL. Paste a YouTube, SoundCloud, or Spotify link."
    )
