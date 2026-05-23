"""Manuella import-flöden via webUI.

Tre flöden, alla coroutiner som matar broadcaster med logg-rader:

1. YouTube-URL (video eller spellista) -> triggar run.py med --url, samma
   arkiv/post-proc-kedja som det schemalagda jobbet.
2. RSS-enclosure-URL -> curl mp3 till temp -> last metadata ur befintlig ID3
   -> bygg konvention-namn -> tagga -> flytta till poddmappen.
3. Lokal filsokvag -> samma som RSS-flodet, fast filen finns redan pa disken.

RSS- och lokal-flodena kraver att kallfilen har ID3-taggar (atminstone TIT2 +
TDRC). Saknas dessa returneras felmeddelande; lagg till manuellt i en
tag-editor forst.
"""
import asyncio
import shutil
import sys
from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError

from app.config import PROJECT_ROOT, settings
from app.jobs import _stream_subprocess
from downloader import episode_index, naming, tagging
from downloader.config import load_config


def _find_show(name):
    cfg = load_config(settings.config_path)
    for s in cfg.shows:
        if s.name == name:
            return s
    raise ValueError(f"Okänd podd: {name!r}")


async def import_youtube(url, show_name, track_kind, broadcaster):
    """Trigga run.py --url för en enskild video eller annan spellista."""
    args = [sys.executable, "run.py",
            "--config", settings.config_path,
            "--url", url,
            "--show", show_name,
            "--track", track_kind]
    await broadcaster.publish({"event": "start",
                               "args": ["import-youtube", show_name, track_kind]})
    await broadcaster.publish({"event": "log", "line": f"URL: {url}"})
    code = 1
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        code = await _stream_subprocess(proc, broadcaster)
    except Exception as exc:
        await broadcaster.publish({"event": "error", "message": str(exc)})
    finally:
        await broadcaster.publish({"event": "end", "code": code})


async def import_rss_enclosure(url, show_name, broadcaster):
    """Ladda en enclosure-URL (en mp3) och städa in den."""
    await broadcaster.publish({"event": "start",
                               "args": ["import-rss", show_name]})
    await broadcaster.publish({"event": "log", "line": f"URL: {url}"})
    code = 1
    src: Path | None = None
    try:
        show = _find_show(show_name)
        if not show.audio or not show.audio.enabled:
            await broadcaster.publish({"event": "error",
                                       "message": "Ljudspår ej aktivt för podden"})
            return
        tmp_dir = settings.state_dir / "tmp" / f"import_rss_{_slug(show_name)}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fname = url.rsplit("/", 1)[-1].split("?")[0] or "import.mp3"
        if not fname.endswith(".mp3"):
            fname += ".mp3"
        src = tmp_dir / fname

        await broadcaster.publish({"event": "log", "line": f"Laddar ner till {src}"})
        proc = await asyncio.create_subprocess_exec(
            "curl", "-fsSL", "-A", "Mozilla/5.0", "-o", str(src), url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        curl_code = await _stream_subprocess(proc, broadcaster, prefix="[curl] ")
        if curl_code != 0 or not src.exists() or src.stat().st_size < 1024:
            await broadcaster.publish({"event": "error",
                                       "message": "Nedladdning misslyckades"})
            return
        await broadcaster.publish({"event": "log",
                                   "line": f"Hämtad: {src.stat().st_size/1e6:.1f} MB"})
        if await _apply_id3_and_move(src, show, broadcaster, source="rss"):
            code = 0
    except Exception as exc:
        await broadcaster.publish({"event": "error", "message": str(exc)})
    finally:
        if src is not None:
            src.unlink(missing_ok=True)
        await broadcaster.publish({"event": "end", "code": code})


async def import_local_file(path_str, show_name, broadcaster):
    """Importera en redan-på-disken-fil till poddmappen."""
    await broadcaster.publish({"event": "start",
                               "args": ["import-local", show_name, path_str]})
    code = 1
    src: Path | None = None
    try:
        src_orig = Path(path_str)
        if not src_orig.is_file():
            await broadcaster.publish({"event": "error",
                                       "message": f"Filen finns inte: {src_orig}"})
            return
        show = _find_show(show_name)
        # Kopiera till temp så orginalet bevaras tills flytt lyckats.
        tmp_dir = settings.state_dir / "tmp" / f"import_local_{_slug(show_name)}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        src = tmp_dir / src_orig.name
        shutil.copy2(src_orig, src)
        if await _apply_id3_and_move(src, show, broadcaster, source="local"):
            code = 0
    except Exception as exc:
        await broadcaster.publish({"event": "error", "message": str(exc)})
    finally:
        if src is not None:
            src.unlink(missing_ok=True)
        await broadcaster.publish({"event": "end", "code": code})


async def _apply_id3_and_move(src: Path, show, broadcaster, source) -> bool:
    """Las metadata ur ID3, bygg konventionsfilnamn, tagga, flytta.

    Returnerar True vid lyckad import, False annars (felmeddelande publiceras).
    """
    try:
        tags = ID3(src)
    except ID3NoHeaderError:
        await broadcaster.publish({"event": "error",
                                   "message": "Källfilen saknar ID3-taggar. "
                                   "Lägg till åtminstone TIT2 + TDRC först."})
        return False

    title_raw = tags["TIT2"].text[0] if "TIT2" in tags else None
    date_raw = str(tags["TDRC"].text[0]) if "TDRC" in tags else None
    comm = tags.getall("COMM")
    comment = str(comm[0].text[0]) if comm and comm[0].text else ""

    if not title_raw or not date_raw:
        await broadcaster.publish({"event": "error",
                                   "message": "ID3 saknar TIT2 eller TDRC"})
        return False

    # Parsa numret ur titeln med showens regex (kan ge None -> nummerlös).
    num_raw, clean_title = naming.parse_title(title_raw, show.title_regex)
    iso = date_raw[:10]
    upload_date = iso.replace("-", "") if len(iso) == 10 else "00000000"
    ext = src.suffix.lstrip(".") or "mp3"
    filename = naming.build_filename(upload_date, num_raw, clean_title, ext,
                                     4, "omit")
    target = Path(show.audio.output_dir) / filename

    if target.exists():
        await broadcaster.publish({"event": "error",
                                   "message": f"Målfil finns redan: {target}"})
        return False

    title_tag = (f"{num_raw.zfill(4)} - {clean_title}"
                 if num_raw is not None else clean_title)
    await broadcaster.publish({"event": "log",
                               "line": f"Parsad: titel={clean_title!r} num={num_raw} datum={iso}"})
    tagging.tag_file(str(src), title=title_tag, album=show.name,
                     artist=show.name, genre="Podcast", track_raw=num_raw,
                     date_iso=iso, comment=comment)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    await broadcaster.publish({"event": "log", "line": f"Skapad: {target}"})

    episode_index.save_episode(
        show.name,
        yt_id=None,
        title=clean_title,
        upload_date=iso.replace("-", "") if iso else None,
        duration=None,
        thumbnail_url=None,
        source=source,
        audio_path=str(target),
    )
    return True


def _slug(name):
    import re
    import unicodedata
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r'[^a-z0-9]+', '_', n.lower()).strip('_') or "show"
