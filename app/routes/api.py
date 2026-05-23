"""JSON-endpoints: trigga jobb och import, avsnittslista, radera/reimport, SSE."""
import json
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import importer, jobs
from app.archive import remove_id
from app.config import PROJECT_ROOT, settings
from app.episodes import find_video_file
from downloader import episode_index
from downloader.config import load_config
from downloader.lock import Lock, is_held

router = APIRouter()


def _find_show(name):
    cfg = load_config(settings.config_path)
    for s in cfg.shows:
        if s.name == name:
            return s
    return None


def _submit(runner, coro):
    if not runner.submit(coro):
        return JSONResponse({"ok": False, "error": "Körning pågår redan"},
                            status_code=409)
    return {"ok": True}


# ---- shows + status ----

@router.get("/shows")
def shows():
    cfg = load_config(settings.config_path)
    return {"shows": [{"name": s.name,
                       "audio": bool(s.audio and s.audio.enabled),
                       "video": bool(s.video and s.video.enabled)}
                      for s in cfg.shows]}


@router.get("/episodes/{ep_id}/transcript")
def get_transcript(ep_id: str, show: str):
    meta = episode_index.find(show, ep_id)
    if not meta or not meta.get("transcript_path"):
        return JSONResponse({"ok": False, "error": "Inget transcript"}, status_code=404)
    path = Path(meta["transcript_path"])
    if not path.is_file():
        return JSONResponse({"ok": False, "error": "Transcript-fil saknas"}, status_code=404)
    raw = path.read_text(encoding="utf-8")
    return {"ok": True, "cues": _parse_vtt(raw), "raw": raw}


@router.post("/episodes/{ep_id}/fetch-transcript")
async def fetch_transcript_now(request: Request, ep_id: str):
    """Hamta YouTube-undertexter for ett redan importerat avsnitt."""
    import re as _re
    import unicodedata as _ud
    p = await request.json()
    show_name = p.get("show")
    if not show_name:
        return JSONResponse({"ok": False, "error": "show kravs"}, status_code=400)
    show = _find_show(show_name)
    if show is None:
        return JSONResponse({"ok": False, "error": "okand podd"}, status_code=404)
    meta = episode_index.find(show_name, ep_id)
    if not meta:
        return JSONResponse({"ok": False, "error": "okand avsnitt"},
                            status_code=404)
    if not meta.get("yt_id"):
        return JSONResponse({"ok": False,
                             "error": "endast YouTube-avsnitt kan hamta undertexter"},
                            status_code=400)

    from downloader import transcripts as _transcripts
    slug = _re.sub(r'[^a-z0-9]+', '_',
                   _ud.normalize("NFKD", show_name).encode("ascii", "ignore")
                   .decode().lower()).strip('_') or "show"
    tr_dir = settings.state_dir / "transcripts" / slug

    lock = Lock()
    if not lock.acquire():
        return JSONResponse({"ok": False, "error": "körning pågår, vänta"},
                            status_code=409)
    try:
        sub_path = _transcripts.fetch_subs(meta["yt_id"], tr_dir)
    finally:
        lock.release()

    if not sub_path:
        return JSONResponse({"ok": False,
                             "error": "Inga undertexter hittades på YouTube"},
                            status_code=404)

    episode_index.save_episode(show_name, yt_id=meta["yt_id"],
                               transcript_path=str(sub_path))
    request.app.state.episodes.invalidate()
    return {"ok": True, "path": str(sub_path)}


_VTT_TS = re.compile(r'(\d+:\d+(?::\d+)?\.\d+)\s*-->\s*(\d+:\d+(?::\d+)?\.\d+)')


def _parse_vtt(text):
    """Tunn VTT-parser: returnerar [{start, end, text}]. Tar bort YouTube-
    auto-subs-taggar (<c.colorXXXX>...) och dubbletter (auto-subs sliding-window).
    """
    cues = []
    seen_text = set()
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.strip().splitlines()
        ts_line = next((ln for ln in lines if _VTT_TS.search(ln)), None)
        if ts_line is None:
            continue
        m = _VTT_TS.search(ts_line)
        body = " ".join(ln for ln in lines if ln is not ts_line and ln != ts_line).strip()
        # alt: body = bara raderna efter timestamp
        idx = lines.index(ts_line)
        body = " ".join(lines[idx + 1:]).strip()
        # rensa tag-noise
        body = re.sub(r'<[^>]+>', '', body)
        body = re.sub(r'\s+', ' ', body).strip()
        if not body or body in seen_text:
            continue
        seen_text.add(body)
        cues.append({"start": m.group(1), "end": m.group(2), "text": body})
    return cues


@router.get("/runs")
def list_runs():
    """Senaste korningarnas sammanfattningar."""
    import json
    runs_dir = settings.state_dir / "runs"
    if not runs_dir.is_dir():
        return {"runs": []}
    files = sorted(runs_dir.glob("*.json"), reverse=True)[:50]
    out = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "started_at": d.get("started_at"),
            "exit_code": d.get("exit_code"),
            "new_files": d.get("new_files", 0),
            "errors": d.get("errors", 0),
            "job_failures": d.get("job_failures", 0),
            "args": d.get("args", {}),
        })
    return {"runs": out}


@router.get("/runs/{ts}")
def get_run(ts: str):
    import json
    runs_dir = settings.state_dir / "runs"
    path = runs_dir / f"{ts}.json"
    if not path.is_file():
        return JSONResponse({"ok": False, "error": "not found"},
                            status_code=404)
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/health")
def health(request: Request):
    """Simpel health-check for Docker HEALTHCHECK och Unraid-monitor."""
    return {"ok": True,
            "running": request.app.state.runner.is_running(),
            "locked": is_held()}


@router.get("/run/status")
def run_status(request: Request):
    return {"running": request.app.state.runner.is_running(),
            "locked": is_held()}


# ---- avsnittslista ----

@router.get("/episodes")
async def get_episodes(request: Request, refresh: int = 0):
    return await request.app.state.episodes.get(refresh=bool(refresh))


@router.delete("/episodes/{ep_id}")
async def delete_episode(request: Request, ep_id: str):
    p = await request.json()
    show_name = p.get("show")
    track_kind = p.get("track")
    keep_archive = bool(p.get("keep_archive"))
    if not show_name or track_kind not in ("audio", "video"):
        return JSONResponse({"ok": False,
                             "error": "show och track (audio|video) kravs"}, 400)
    show = _find_show(show_name)
    if show is None:
        return JSONResponse({"ok": False, "error": "okand podd"}, 404)
    track = getattr(show, track_kind)
    if track is None:
        return JSONResponse({"ok": False, "error": "spar saknas"}, 400)

    lock = Lock()
    if not lock.acquire():
        return JSONResponse({"ok": False, "error": "körning pågår, vänta"},
                            status_code=409)
    file_deleted = False
    archive_deleted = False
    try:
        if ep_id.startswith("local_"):
            # Bonus-avsnitt: anvand metadata for sokvag.
            meta = episode_index.find(show_name, ep_id)
            if meta is None:
                return JSONResponse({"ok": False,
                                     "error": "okand bonus-avsnitt"}, 404)
            path_str = meta.get(f"{track_kind}_path")
            if path_str and Path(path_str).is_file():
                Path(path_str).unlink()
                file_deleted = True
            episode_index.set_path(show_name, ep_id, track_kind, None)
        else:
            # YouTube-id: anvand arkiv + filsokning.
            if track_kind == "video":
                f = find_video_file(show, ep_id)
                if f is not None:
                    f.unlink()
                    file_deleted = True
            else:
                # Audio: filnamnet saknar id; ta filsokvagen ur metadata-katalogen.
                meta_pre = episode_index.find(show_name, ep_id)
                ap = meta_pre.get("audio_path") if meta_pre else None
                if ap and Path(ap).is_file():
                    Path(ap).unlink()
                    file_deleted = True
            if not keep_archive:
                archive_deleted = remove_id(track.archive, ep_id)
            episode_index.set_path(show_name, ep_id, track_kind, None)
        # Om bada paths nu rensade och inget arkiv -> ta bort posten helt.
        meta = episode_index.find(show_name, ep_id)
        if (meta and not meta.get("audio_path") and not meta.get("video_path")
                and not meta.get("yt_id")):
            episode_index.remove_episode(show_name, ep_id)
    finally:
        lock.release()

    request.app.state.episodes.invalidate()
    return {"ok": True, "file_deleted": file_deleted,
            "archive_deleted": archive_deleted}


@router.post("/episodes/{video_id}/reimport")
async def reimport_episode(request: Request, video_id: str):
    runner = request.app.state.runner
    p = await request.json()
    show_name = p.get("show")
    track_kind = p.get("track")
    if not show_name or track_kind not in ("audio", "video"):
        return JSONResponse({"ok": False,
                             "error": "show och track (audio|video) kravs"}, 400)
    show = _find_show(show_name)
    if show is None:
        return JSONResponse({"ok": False, "error": "okand podd"}, 404)
    coro = _reimport_coro(video_id, show, track_kind, runner.broadcaster,
                          request.app.state.episodes)
    return _submit(runner, coro)


async def _reimport_coro(video_id, show, track_kind, broadcaster, episodes_svc):
    """Radera + trigga run.py --url for ett specifikt avsnitt."""
    import asyncio
    await broadcaster.publish({"event": "start",
                               "args": ["reimport", show.name, track_kind, video_id]})
    code = 1
    try:
        lock = Lock()
        if not lock.acquire():
            await broadcaster.publish({"event": "error",
                                       "message": "Körning pågår, försök igen senare"})
            return
        try:
            track = getattr(show, track_kind)
            if track_kind == "video":
                f = find_video_file(show, video_id)
                if f is not None:
                    f.unlink()
                    await broadcaster.publish({"event": "log",
                                               "line": f"Raderade {f.name}"})
            if remove_id(track.archive, video_id):
                await broadcaster.publish({"event": "log",
                                           "line": "Tog bort arkivrad"})
        finally:
            lock.release()
        episodes_svc.invalidate()

        url = f"https://www.youtube.com/watch?v={video_id}"
        await broadcaster.publish({"event": "log",
                                   "line": f"Hämtar {url}"})
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "run.py",
            "--config", settings.config_path,
            "--url", url, "--show", show.name, "--track", track_kind,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        code = await jobs._stream_subprocess(proc, broadcaster)
    except Exception as exc:
        await broadcaster.publish({"event": "error", "message": str(exc)})
    finally:
        episodes_svc.invalidate()
        await broadcaster.publish({"event": "end", "code": code})


# ---- kor-nu + manuell import ----

@router.post("/run")
async def trigger_run(request: Request):
    runner = request.app.state.runner
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    args: list[str] = []
    if show := payload.get("show"):
        args += ["--show", show]
    if track := payload.get("track"):
        args += ["--track", track]
    if items := payload.get("playlist_items"):
        args += ["--playlist-items", str(items)]
    if payload.get("dry_run"):
        args.append("--dry-run")
    return _submit(runner, jobs.run_py_subprocess(args, runner.broadcaster))


@router.get("/import/preview")
async def import_preview(url: str):
    """Hamtar YouTube-metadata och bygger forslag for varje (podd, spar)-kombo."""
    import asyncio
    import json as _json
    import os as _os
    from downloader import naming
    ytdlp = _os.environ.get("YTDLP_BIN", "yt-dlp")
    proc = await asyncio.create_subprocess_exec(
        ytdlp, "--dump-json", "--skip-download", "--no-warnings", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0 or not stdout.strip():
        msg = stderr.decode("utf-8", "replace")[:200] or "okand fel"
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    try:
        meta = _json.loads(stdout.decode("utf-8", "replace").splitlines()[0])
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    cfg = load_config(settings.config_path)
    defaults = cfg.defaults
    suggestions = []
    for show in cfg.shows:
        for kind in ("audio", "video"):
            track = getattr(show, kind)
            if track is None or not track.enabled:
                continue
            num_raw, clean_title = naming.parse_title(meta.get("title", ""),
                                                      show.title_regex)
            padding = defaults.get("number_padding", 4)
            missing_mode = defaults.get("on_missing_number", "omit")
            date = meta.get("upload_date") or "00000000"
            ext = (defaults.get("audio_format", "m4a") if kind == "audio"
                   else defaults.get("video_container", "mp4"))
            suffix = meta.get("id") if kind == "video" else None
            filename = naming.build_filename(date, num_raw, clean_title, ext,
                                             padding, missing_mode, suffix=suffix)
            suggestions.append({
                "show": show.name,
                "track": kind,
                "predicted_filename": filename,
                "matched_regex": num_raw is not None,
                "output_dir": track.output_dir,
            })
    return {
        "ok": True,
        "id": meta.get("id"),
        "title": meta.get("title"),
        "upload_date": meta.get("upload_date"),
        "duration": meta.get("duration"),
        "thumbnail": meta.get("thumbnail"),
        "description": (meta.get("description") or "")[:500],
        "suggestions": suggestions,
    }


@router.post("/import/youtube")
async def import_youtube(request: Request):
    runner = request.app.state.runner
    p = await request.json()
    url = (p.get("url") or "").strip()
    show = p.get("show")
    track = p.get("track") or "audio"
    if not url or not show:
        return JSONResponse({"ok": False, "error": "url och show kravs"}, 400)
    return _submit(runner,
                   importer.import_youtube(url, show, track, runner.broadcaster))


@router.post("/import/rss")
async def import_rss(request: Request):
    runner = request.app.state.runner
    p = await request.json()
    url = (p.get("url") or "").strip()
    show = p.get("show")
    if not url or not show:
        return JSONResponse({"ok": False, "error": "url och show kravs"}, 400)
    return _submit(runner,
                   importer.import_rss_enclosure(url, show, runner.broadcaster))


@router.post("/import/local")
async def import_local(request: Request):
    runner = request.app.state.runner
    p = await request.json()
    path = (p.get("path") or "").strip()
    show = p.get("show")
    if not path or not show:
        return JSONResponse({"ok": False, "error": "path och show kravs"}, 400)
    return _submit(runner,
                   importer.import_local_file(path, show, runner.broadcaster))


# ---- SSE ----

@router.get("/run/events")
async def run_events(request: Request):
    runner = request.app.state.runner
    queue = await runner.broadcaster.subscribe()

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                msg = await queue.get()
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        finally:
            runner.broadcaster.unsubscribe(queue)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
