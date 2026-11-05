# Demolec

Personal media converter / downloader for **YouTube**, **SoundCloud**, and **Spotify**.

Paste a song, video, or playlist link → choose **MP3**, **WAV**, or **MP4** → download.

### Playlist flow

1. Paste a Spotify / SoundCloud / YouTube playlist link and click **Resolve link**
2. Browse the resolved track list
3. Multi-select tracks, or use **Download** on a single row
4. **Download selected** or **Download all**
5. Multiple files come back as a `.zip` you can extract locally

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/download.html) on your `PATH`

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python run.py
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

## Notes

- **YouTube / SoundCloud** download directly via `yt-dlp`.
- **Spotify** streams are DRM-protected, so Demolec reads the public track list and downloads the best YouTube match for each song (metadata match — not Spotify’s own audio file).
- **WAV** is max-quality **24-bit PCM** from the best available source (no size cap — files can be heavy).
- Playlists / multi-select downloads are packaged into a `.zip` when there is more than one file.
- Only use this for media you have the right to download / for personal archival where allowed.
