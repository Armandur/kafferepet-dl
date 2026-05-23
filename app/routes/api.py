"""JSON-endpoints: trigga jobb och import, avsnittslista, radera/reimport, SSE."""
import json
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import importer, jobs
from app.archive import remove_id
from app.config import PROJECT_ROOT, settings
from app.episodes import find_video_file
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


@router.get("/run/status")
def run_status(request: Request):
    return {"running": request.app.state.runner.is_running(),
            "locked": is_held()}


# ---- avsnittslista ----

@router.get("/episodes")
async def get_episodes(request: Request, refresh: int = 0):
    return await request.app.state.episodes.get(refresh=bool(refresh))


@router.delete("/episodes/{video_id}")
async def delete_episode(request: Request, video_id: str):
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
    try:
        file_deleted = False
        archive_deleted = False
        if track_kind == "video":
            f = find_video_file(show, video_id)
            if f is not None:
                f.unlink()
                file_deleted = True
        # Audio: filnamnet har inte id - vi raderar inte filen automatiskt.
        if not keep_archive:
            archive_deleted = remove_id(track.archive, video_id)
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
