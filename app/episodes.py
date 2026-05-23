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
from downloader import episode_index, naming
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

            local_meta = episode_index.load(show.name)
            local_by_yt = {m["yt_id"]: m for m in local_meta if m.get("yt_id")}

            episodes = []
            for p_ep in playlist:
                vid = p_ep["id"]
                episodes.append(self._make(show, vid, p_ep,
                                           vid in audio_ids, vid in video_ids,
                                           in_playlist=True, defaults=defaults,
                                           local=local_by_yt.get(vid)))
            extras = sorted((audio_ids | video_ids) - playlist_ids)
            for vid in extras:
                local = local_by_yt.get(vid)
                # Anvand lokal metadata om finns sa arkivposter behaller titel/datum
                ep_data = {"id": vid, "title": None}
                if local:
                    ep_data.update({
                        "title": local.get("title"),
                        "thumbnail": local.get("thumbnail_url"),
                        "duration": local.get("duration"),
                        "upload_date": local.get("upload_date"),
                    })
                episodes.append(self._make(show, vid, ep_data,
                                           vid in audio_ids, vid in video_ids,
                                           in_playlist=False, defaults=defaults,
                                           local=local))
            # Bonus: lokal metadata utan yt_id (RSS-/lokal-import).
            bonus = [self._make_bonus(show, m)
                     for m in local_meta if not m.get("yt_id")]
            # Kanal-extras: videor pa kanalen som matchar showens regex men
            # inte ar i spellistan eller arkiven.
            channel_extras = await self._fetch_channel_extras(
                show, defaults,
                exclude_ids=playlist_ids | audio_ids | video_ids)
            shows_out.append({"name": show.name,
                              "episodes": episodes,
                              "bonus": bonus,
                              "channel_extras": channel_extras})
        return {"shows": shows_out, "fetched_at": time.time()}

    async def _fetch_channel_extras(self, show, defaults, exclude_ids):
        """Skannar kanalen for videor som matchar showens regex men inte
        finns i spellistan/arkiven. Hybridstrategi: flat-playlist for snabb
        listning + per-video enrich for att fa upload_date (som flat-playlist
        saknar). Filtrerar positivt pa title_regex sa Branda kakor-videor inte
        hamnar under Kafferepet och tvartom (poddarna delar ofta kanal).
        """
        if not show.channel_url:
            return []
        ytdlp = os.environ.get("YTDLP_BIN", "yt-dlp")
        proc = await asyncio.create_subprocess_exec(
            ytdlp, "--flat-playlist", "--playlist-end", "50", "--dump-json",
            "--no-warnings", show.channel_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        candidates = []
        for line in stdout.decode("utf-8", "replace").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            vid = d.get("id")
            if not vid or vid in exclude_ids:
                continue
            title = d.get("title") or ""
            if naming.parse_title(title, show.title_regex)[0] is None:
                continue
            thumb = d.get("thumbnail")
            if not thumb and d.get("thumbnails"):
                thumb = d["thumbnails"][-1].get("url")
            candidates.append({"id": vid, "title": title, "thumbnail": thumb,
                               "duration": d.get("duration")})

        # Anrika med upload_date (flat-playlist saknar det) - parallellt.
        await asyncio.gather(*[self._enrich_video(c) for c in candidates])

        out = []
        for c in candidates:
            ep = self._make(show, c["id"], c, False, False,
                            in_playlist=False, defaults=defaults)
            ep["is_channel_extra"] = True
            out.append(ep)
        return out

    async def _enrich_video(self, c):
        ytdlp = os.environ.get("YTDLP_BIN", "yt-dlp")
        proc = await asyncio.create_subprocess_exec(
            ytdlp, "--dump-json", "--skip-download", "--no-warnings",
            f"https://www.youtube.com/watch?v={c['id']}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if not stdout.strip():
            return
        try:
            d = json.loads(stdout.decode("utf-8", "replace").splitlines()[0])
        except Exception:
            return
        if d.get("upload_date"):
            c["upload_date"] = d["upload_date"]
        if d.get("duration"):
            c["duration"] = d["duration"]
        if d.get("thumbnail"):
            c["thumbnail"] = d["thumbnail"]

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

    def _make(self, show, vid, ep_data, in_audio, in_video, in_playlist,
              defaults, local=None):
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

    def _make_bonus(self, show, meta):
        """Avsnitt fran lokal metadata utan YouTube-id (RSS- eller lokal-import)."""
        has_audio = bool(meta.get("audio_path"))
        has_video = bool(meta.get("video_path"))

        def st(track, present):
            if track is None or not track.enabled:
                return {"status": "disabled"}
            return {"status": "imported" if present else "missing",
                    "path": (meta.get("audio_path") if present and track is show.audio
                             else (meta.get("video_path") if present else None))}

        return {
            "id": meta["id"],
            "title": meta.get("title"),
            "thumbnail": meta.get("thumbnail_url"),
            "duration": meta.get("duration"),
            "upload_date": meta.get("upload_date"),
            "in_playlist": False,
            "is_bonus": True,
            "source": meta.get("source"),
            "audio": st(show.audio, has_audio),
            "video": st(show.video, has_video),
            "predicted": {},
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
