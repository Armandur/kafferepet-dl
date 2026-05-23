"""Lokal metadata-katalog per show: vad har importerats och varifran.

WebUI:n laser indexet for att:
  - Visa avsnitt utan YouTube-id (RSS-/lokal-importer som sommarkakor).
  - Behalla titel/datum/thumbnail aven om YouTube raderar videon.

Indexet ligger pa /state/episodes_<slug>.json. Skrivs av postprocess.py
(YouTube-flode) och app.importer (RSS/lokal-flode). En fil per show.
"""
import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path


def _slug(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_') or "show"


def _state_dir() -> Path:
    return Path(os.environ.get("STATE_DIR", "/state"))


def _index_path(show_name) -> Path:
    return _state_dir() / f"episodes_{_slug(show_name)}.json"


def load(show_name) -> list[dict]:
    p = _index_path(show_name)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("episodes", [])
    except Exception:
        return []


def save_episode(show_name, *, yt_id=None, title=None, upload_date=None,
                 duration=None, thumbnail_url=None, source="unknown",
                 audio_path=None, video_path=None):
    """Lagger till eller uppdaterar en post. Idempotent per id."""
    eps = load(show_name)
    ep_id = yt_id or _hash_id(title, upload_date)
    existing = next((e for e in eps if e.get("id") == ep_id), None)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if existing is None:
        eps.append({
            "id": ep_id, "yt_id": yt_id, "title": title,
            "upload_date": upload_date, "duration": duration,
            "thumbnail_url": thumbnail_url, "source": source,
            "audio_path": audio_path, "video_path": video_path,
            "imported_at": now,
        })
    else:
        # uppdatera fält där vi har nya värden; bevara existerande annars
        for k, v in (("title", title), ("upload_date", upload_date),
                     ("duration", duration), ("thumbnail_url", thumbnail_url),
                     ("source", source)):
            if v is not None:
                existing[k] = v
        if audio_path is not None:
            existing["audio_path"] = audio_path
        if video_path is not None:
            existing["video_path"] = video_path
        existing["imported_at"] = now

    _write(show_name, eps)


def remove_episode(show_name, ep_id) -> bool:
    eps = load(show_name)
    kept = [e for e in eps if e.get("id") != ep_id]
    if len(kept) == len(eps):
        return False
    _write(show_name, kept)
    return True


def set_path(show_name, ep_id, kind, path) -> bool:
    """Satter eller rensar audio_path/video_path. kind = 'audio'|'video'.
    path=None rensar. Returnerar True om posten fanns och uppdaterades."""
    field = f"{kind}_path"
    eps = load(show_name)
    for e in eps:
        if e.get("id") == ep_id:
            e[field] = path
            _write(show_name, eps)
            return True
    return False


def find(show_name, ep_id) -> dict | None:
    return next((e for e in load(show_name) if e.get("id") == ep_id), None)


def _write(show_name, eps):
    p = _index_path(show_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "episodes": eps},
                            ensure_ascii=False, indent=2),
                 encoding="utf-8")


def _hash_id(title, upload_date) -> str:
    h = hashlib.sha1(f"{title or ''}|{upload_date or ''}".encode()).hexdigest()[:12]
    return f"local_{h}"
