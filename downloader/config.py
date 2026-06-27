"""Inlasning och validering av config.yaml."""
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULTS = {
    "audio_format": "m4a",
    "audio_quality": "0",
    "video_format": "bv*+ba/b",
    "video_container": "mp4",
    "embed_metadata": True,
    "embed_thumbnail": True,
    "number_padding": 4,
    "on_missing_number": "omit",
    "filename_separator": " - ",
    "write_description": False,
    "dateafter": None,
    "sleep_requests": 2,
    "concurrent_fragments": 4,
    "tmp_root": "/state/tmp",
    "run_once": False,
}


@dataclass
class TrackCfg:
    kind: str
    enabled: bool
    output_dir: str
    archive: str
    retention_days: int = 0


@dataclass
class ShowCfg:
    name: str
    playlist_id: str
    title_regex: str
    audio: "TrackCfg | None"
    video: "TrackCfg | None"
    channel_url: str = ""
    title_template: str = ""


@dataclass
class Config:
    defaults: dict
    shows: list


def _require(d, key, where):
    if key not in d or d[key] in (None, ""):
        raise ValueError(f"config: '{key}' saknas under {where}")
    return d[key]


def _track(kind, raw):
    if raw is None:
        return None
    return TrackCfg(
        kind=kind,
        enabled=bool(raw.get("enabled", False)),
        output_dir=_require(raw, "output_dir", f"tracks.{kind}"),
        archive=_require(raw, "archive", f"tracks.{kind}"),
        retention_days=int(raw.get("retention_days", 0)),
    )


def load_config(path):
    """Laser config.yaml, slar samman med defaults och validerar."""
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("config: filen ar tom eller felformaterad")

    defaults = dict(_DEFAULTS)
    defaults.update(raw.get("defaults") or {})
    if defaults["on_missing_number"] not in ("omit", "placeholder", "skip"):
        raise ValueError("config: on_missing_number maste vara omit/placeholder/skip")

    shows = []
    for s in raw.get("shows") or []:
        name = _require(s, "name", "shows[]")
        regex = _require(s, "title_regex", f"show '{name}'")
        try:
            compiled = re.compile(regex)
        except re.error as exc:
            raise ValueError(f"config: ogiltig title_regex for '{name}': {exc}")
        if "title" not in compiled.groupindex:
            raise ValueError(f"config: title_regex for '{name}' saknar grupp 'title'")
        tracks = s.get("tracks") or {}
        shows.append(ShowCfg(
            name=name,
            playlist_id=_require(s, "playlist_id", f"show '{name}'"),
            title_regex=regex,
            audio=_track("audio", tracks.get("audio")),
            video=_track("video", tracks.get("video")),
            channel_url=(s.get("channel_url") or "").strip(),
            title_template=(s.get("title_template") or "").strip(),
        ))
    if not shows:
        raise ValueError("config: inga 'shows' definierade")
    return Config(defaults=defaults, shows=shows)


_MAX_BACKUPS = 10


def save_config(path, content):
    """Validera, backa upp och skriv config-text atomiskt.

    Stegen sker i ordning: skriv content till en temp-fil i samma katalog och
    kor load_config(temp) for validering. Validerar det inte tas temp bort och
    undantaget propagerar (anroparen returnerar 400). Annars kopieras nuvarande
    config till en tidsstamplad backup (de 10 senaste behalls) innan temp-filen
    flyttas pa plats med os.replace (atomiskt). Returnerar backupfilens namn,
    eller None om ingen backup gjordes (filen fanns inte sedan tidigare).
    """
    cfg_path = Path(path)
    cfg_dir = cfg_path.parent
    tmp_path = cfg_dir / f"{cfg_path.name}.tmp-{os.getpid()}"

    tmp_path.write_text(content, encoding="utf-8")
    try:
        load_config(tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    backup_name = None
    if cfg_path.exists():
        backup_name = f"{cfg_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(cfg_path, cfg_dir / backup_name)
        _prune_backups(cfg_dir, cfg_path.name)

    os.replace(tmp_path, cfg_path)
    return backup_name


def _prune_backups(cfg_dir, base_name):
    """Behall bara de _MAX_BACKUPS senaste .bak-filerna for configen."""
    backups = sorted(cfg_dir.glob(f"{base_name}.bak-*"))
    for old in backups[:-_MAX_BACKUPS]:
        old.unlink(missing_ok=True)
