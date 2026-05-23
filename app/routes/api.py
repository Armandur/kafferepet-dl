"""JSON-endpoints: trigga jobb och import, status, SSE-strom."""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import importer, jobs
from app.config import settings
from downloader.config import load_config

router = APIRouter()


@router.get("/shows")
def shows():
    """Listar konfigurerade poddar for dropdowns i UIt."""
    cfg = load_config(settings.config_path)
    return {"shows": [{"name": s.name,
                       "audio": bool(s.audio and s.audio.enabled),
                       "video": bool(s.video and s.video.enabled)}
                      for s in cfg.shows]}


@router.get("/run/status")
def run_status(request: Request):
    return {"running": request.app.state.runner.is_running()}


def _submit(runner, coro):
    if not runner.submit(coro):
        return JSONResponse({"ok": False, "error": "Körning pågår redan"},
                            status_code=409)
    return {"ok": True}


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
        return JSONResponse({"ok": False, "error": "url och show kravs"},
                            status_code=400)
    return _submit(runner,
                   importer.import_youtube(url, show, track, runner.broadcaster))


@router.post("/import/rss")
async def import_rss(request: Request):
    runner = request.app.state.runner
    p = await request.json()
    url = (p.get("url") or "").strip()
    show = p.get("show")
    if not url or not show:
        return JSONResponse({"ok": False, "error": "url och show kravs"},
                            status_code=400)
    return _submit(runner,
                   importer.import_rss_enclosure(url, show, runner.broadcaster))


@router.post("/import/local")
async def import_local(request: Request):
    runner = request.app.state.runner
    p = await request.json()
    path = (p.get("path") or "").strip()
    show = p.get("show")
    if not path or not show:
        return JSONResponse({"ok": False, "error": "path och show kravs"},
                            status_code=400)
    return _submit(runner,
                   importer.import_local_file(path, show, runner.broadcaster))


@router.get("/run/events")
async def run_events(request: Request):
    """Server-Sent Events: nya rader fran pagaende/kommande korningar."""
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
