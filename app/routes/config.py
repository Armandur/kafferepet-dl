"""Config-editor: hamta och spara config.yaml (validering + backup)."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from downloader.config import save_config

router = APIRouter()


@router.get("/config")
def get_config():
    path = Path(settings.config_path)
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {"ok": True, "content": content, "path": str(path)}


@router.post("/config")
async def post_config(request: Request):
    p = await request.json()
    content = p.get("content")
    if not isinstance(content, str):
        return JSONResponse({"ok": False, "error": "content (str) krävs"},
                            status_code=400)
    try:
        backup = save_config(settings.config_path, content)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    request.app.state.episodes.invalidate()
    return {"ok": True, "backup": backup}
