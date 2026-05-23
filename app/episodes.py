"""Bygger avsnittslista per podd: spellistans innehall + arkivrader utan
spellistmatch. Korsar arkivfilerna med filsystemet for video-status.

Cachas i minnet 5 min - yt-dlp --flat-playlist tar 2-4s. invalidate() vid
mutationer (radering/reimport) sa nasta GET fragar fritt om data.
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path

from app.archive import read_ids
from app.config import settings
from downloader import naming
from downloader.config import load_config

log = logging.getLogger(__name__)
PLAYLIST_URL = "https://www.youtube.com/playlist?list={}"
CACHE_TTL = 300


class EpisodesService:
    def __init__(self):
        self._cache = None
        self._cache_ts = 0.0
        self._lock = asyncio.Lock()

    async def get(self, refresh=False):
        async with self._lock:
            now = time.time()
            if (not refresh and self._cache
                    and (now - self._cache_ts) < CACHE_TTL):
                return self._cache
            self._cache = await self._build()
            self._cache_ts = now
            return self._cache

    def invalidate(self):
        self._cache = None
        self._cache_ts = 0.0

    async def _build(self):
        cfg = load_config(settings.config_path)
        defaults = cfg.defaults
        shows_out = []
        for show in cfg.shows:
            audio_ids = (read_ids(show.audio.archive)
                         if show.audio and show.audio.enabled else set())
            video_ids = (read_ids(show.video.archive)
                         if show.video and show.video.enabled else set())
            try:
                playlist = await self._fetch_playlist(show.playlist_id)
            except Exception as exc:
                log.warning("Spellista %s: %s", show.playlist_id, exc)
                playlist = []
            playlist_ids = {p["id"] for p in playlist}

            episodes = []
            for p_ep in playlist:
                vid = p_ep["id"]
                episodes.append(self._make(show, vid, p_ep,
                                           vid in audio_ids, vid in video_ids,
                                           in_playlist=True, defaults=defaults))
            extras = sorted((audio_ids | video_ids) - playlist_ids)
            for vid in extras:
                episodes.append(self._make(show, vid,
                                           {"id": vid, "title": None},
                                           vid in audio_ids, vid in video_ids,
                                           in_playlist=False, defaults=defaults))
            shows_out.append({"name": show.name, "episodes": episodes})
        return {"shows": shows_out, "fetched_at": time.time()}

    async def _fetch_playlist(self, playlist_id):
        """Full metadata per video via --dump-json --skip-download.

        Tar ~10-15s for en spellista (jamfort med ~1s for --flat-playlist), men
        ger upload_date som flat-playlist saknar. Cachas 5 min.
        """
        ytdlp = os.environ.get("YTDLP_BIN", "yt-dlp")
        proc = await asyncio.create_subprocess_exec(
            ytdlp, "--dump-json", "--skip-download", "--no-warnings",
            PLAYLIST_URL.format(playlist_id),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        out = []
        for line in stdout.decode("utf-8", "replace").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            thumb = d.get("thumbnail")
            if not thumb and d.get("thumbnails"):
                thumb = d["thumbnails"][-1].get("url")
            out.append({
                "id": d.get("id"),
                "title": d.get("title"),
                "thumbnail": thumb,
                "duration": d.get("duration"),
                "upload_date": d.get("upload_date"),  # YYYYMMDD
                "description": (d.get("description") or "")[:280],
            })
        return out

    def _make(self, show, vid, ep_data, in_audio, in_video, in_playlist, defaults):
        upload_date = ep_data.get("upload_date")
        return {
            "id": vid,
            "title": ep_data.get("title"),
            "thumbnail": (ep_data.get("thumbnail")
                          or f"https://i.ytimg.com/vi/{vid}/default.jpg"),
            "duration": ep_data.get("duration"),
            "upload_date": upload_date,
            "in_playlist": in_playlist,
            "audio": self._audio_status(show, in_audio),
            "video": self._video_status(show, vid, in_video),
            "predicted": self._predict_filenames(show, vid, ep_data.get("title"),
                                                  upload_date, defaults),
        }

    def _predict_filenames(self, show, vid, title, upload_date, defaults):
        """Returnerar dict med audio/video som filerna SKULLE doapas till."""
        out = {}
        if not title:
            return out
        num_raw, clean = naming.parse_title(title, show.title_regex)
        padding = defaults.get("number_padding", 4)
        missing_mode = defaults.get("on_missing_number", "omit")
        date_str = upload_date or "00000000"
        if show.audio and show.audio.enabled:
            out["audio"] = naming.build_filename(
                date_str, num_raw, clean,
                defaults.get("audio_format", "m4a"),
                padding, missing_mode)
        if show.video and show.video.enabled:
            out["video"] = naming.build_filename(
                date_str, num_raw, clean,
                defaults.get("video_container", "mp4"),
                padding, missing_mode, suffix=vid)
        return out

    def _audio_status(self, show, in_archive):
        if show.audio is None or not show.audio.enabled:
            return {"status": "disabled"}
        return {"status": "imported" if in_archive else "missing"}

    def _video_status(self, show, vid, in_archive):
        if show.video is None or not show.video.enabled:
            return {"status": "disabled"}
        if not in_archive:
            return {"status": "missing"}
        outdir = Path(show.video.output_dir)
        if outdir.is_dir():
            for f in outdir.iterdir():
                if f.is_file() and vid in f.name:
                    return {"status": "imported", "path": str(f)}
        return {"status": "archived_no_file"}


def find_video_file(show, video_id) -> Path | None:
    """Hittar mp4-fil for videon i Plex-arkivet via id-substring i filnamnet."""
    if show.video is None:
        return None
    outdir = Path(show.video.output_dir)
    if not outdir.is_dir():
        return None
    for f in outdir.iterdir():
        if f.is_file() and video_id in f.name:
            return f
    return None
