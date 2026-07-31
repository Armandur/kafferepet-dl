"""Post-processing: parsa titel, ev. tagga, dop om enligt namnkonventionen.

Bada sparen far samma filnamn: 'YYYY-MM-DD - 0000 - Titel.ext'. Numret kraver
regex-parsning av YouTube-titeln, darfor racker inte en ren yt-dlp-outtmpl.

  Ljud:  yt-dlp -> temp-mapp (media + info.json) -> parsa, TAGGA, flytta till
         poddmappen (oftast over filsystemsgrans).
  Video: yt-dlp -> mediafil direkt i Plex-arkivet + info.json i en temp-mapp
         -> parsa, dop om mediafilen pa plats (ingen taggning).

Temp-mappen (info.json-mappen) fungerar som en 'att gora'-ko: korras bade fore
och efter yt-dlp sa en avbruten korning tas upp nasta gang (idempotens).
"""
import errno
import json
import logging
import os
import re
import shutil
import unicodedata
from pathlib import Path

from downloader import episode_index, naming, tagging, transcripts

log = logging.getLogger(__name__)


def process_track_dir(info_dir, media_dir, show, track, defaults, summary):
    """Post-processar ett spar.

    info_dir  - mapp dar yt-dlp:s .info.json ligger.
    media_dir - mapp dar mediafilen ligger (= info_dir for ljud,
                = track.output_dir for video).
    """
    info_dir = Path(info_dir)
    media_dir = Path(media_dir)
    if not info_dir.is_dir():
        return
    ext = (defaults["audio_format"] if track.kind == "audio"
           else defaults["video_container"])

    for info_path in sorted(info_dir.glob("*.info.json")):
        stem = info_path.name[: -len(".info.json")]
        media_path = media_dir / f"{stem}.{ext}"
        if not media_path.exists():
            # Mediafilen ar inte klar (t.ex. avbruten .part). yt-dlp aterupptar
            # den nasta korning - hoppa tyst.
            continue
        try:
            _process_one(info_path, media_path, show, track, defaults, summary)
        except Exception as exc:  # ett trasigt avsnitt far inte blockera resten
            log.error("Post-proc misslyckades for %s: %s", media_path.name, exc)
            summary.add_error(show.name, track.kind, stem)


def _process_one(info_path, media_path, show, track, defaults, summary):
    info = json.loads(info_path.read_text(encoding="utf-8"))
    raw_title = info.get("title", "")
    upload_date = info.get("upload_date", "")
    description = info.get("description", "") or ""

    padding = defaults["number_padding"]
    missing_mode = defaults["on_missing_number"]
    num_raw, clean_title = naming.parse_title(raw_title, show.title_regex)

    if num_raw is None:
        # Raknas som fel: en titel som slutar matcha title_regex betyder oftast
        # att YouTube-titelformatet andrats, och det maste synas i notisen -
        # annars ser korningen ut som en vanlig lyckad.
        summary.add_error(show.name, track.kind, info.get("id") or media_path.stem)
        if missing_mode == "skip":
            log.warning("Avsnitt utan nummer, hoppar (skip): %r", raw_title)
            media_path.unlink(missing_ok=True)
            info_path.unlink(missing_ok=True)
            return
        log.warning("Avsnitt utan parsbart nummer (%s): %r", missing_mode, raw_title)

    ext = media_path.suffix.lstrip(".")
    # Video far video-id sist i filnamnet (= mediafilens id-stem); ljud inte.
    suffix = media_path.stem if track.kind == "video" else None
    filename = naming.build_filename(upload_date, num_raw, clean_title, ext,
                                     padding, missing_mode, suffix=suffix,
                                     title_template=show.title_template)
    target = Path(track.output_dir) / filename

    if target.exists():
        log.warning("Malfil finns redan, hoppar (--no-overwrites): %s", target.name)
        media_path.unlink(missing_ok=True)
        info_path.unlink(missing_ok=True)
        summary.add_skip()
        return

    if track.kind == "audio":
        # Titel-tagg: paddat nummer (spec B3) eller mall. Track-tagg far ratt nummer.
        title_tag = naming.build_title_tag(num_raw, clean_title, padding,
                                           title_template=show.title_template)
        tagging.tag_file(
            str(media_path),
            title=title_tag,
            album=show.name,
            artist=show.name,
            genre="Podcast",
            track_raw=num_raw,
            date_iso=naming.iso_date(upload_date),
            comment=description,
        )

    _safe_move(media_path, target)
    info_path.unlink(missing_ok=True)
    log.info("Skapad: %s", target)
    summary.add_created(show.name, track.kind, str(target))

    # Hamta transcript fran YouTube (om finns) - bara for audio-importer.
    transcript_path = None
    if track.kind == "audio" and info.get("id"):
        state_dir = Path(os.environ.get("STATE_DIR", "/state"))
        tr_dir = state_dir / "transcripts" / _slug(show.name)
        try:
            sub_path = transcripts.fetch_subs(info["id"], tr_dir)
        except Exception as exc:
            log.warning("Transcript-hamtning misslyckades: %s", exc)
            sub_path = None
        if sub_path:
            transcript_path = str(sub_path)
            log.info("Transcript hamtat: %s", sub_path.name)

    # Lagra lokal metadata sa webUI:n ser avsnittet aven om YouTube raderar det.
    episode_index.save_episode(
        show.name,
        yt_id=info.get("id"),
        title=info.get("title"),
        upload_date=info.get("upload_date"),
        duration=info.get("duration"),
        thumbnail_url=info.get("thumbnail"),
        source="youtube",
        audio_path=str(target) if track.kind == "audio" else None,
        video_path=str(target) if track.kind == "video" else None,
        transcript_path=transcript_path,
    )


def _slug(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_') or "show"


def _safe_move(src, dst):
    """Flyttar src till dst atomiskt.

    Inom samma filsystem (video: doper om i Plex-mappen) racker os.replace.
    Over en filsystemsgrans (ljud: /state -> /podcasts) faller vi tillbaka pa
    kopiera-till-<dst>.partial + atomiskt os.replace, sa en avbruten flytt
    aldrig lamnar en halv malfil.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        partial = dst.with_name(dst.name + ".partial")
        shutil.copy2(src, partial)
        os.replace(partial, dst)
        Path(src).unlink(missing_ok=True)
