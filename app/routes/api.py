"""JSON-endpoints: trigga jobb, status, SSE-strom."""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

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
    if not await runner.start(args):
        return JSONResponse({"ok": False, "error": "Körning pågår redan"},
                            status_code=409)
    return {"ok": True, "args": args}


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
