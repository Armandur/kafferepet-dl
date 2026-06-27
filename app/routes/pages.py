"""HTML-vyer."""
from pathlib import Path

from fastapi import APIRouter, Request

from app.config import settings
from downloader.config import load_config

router = APIRouter()


@router.get("/")
def index(request: Request):
    cfg = load_config(settings.config_path)
    return request.app.state.templates.TemplateResponse(
        request, "index.html",
        {"shows": cfg.shows},
    )


@router.get("/import")
def import_page(request: Request):
    cfg = load_config(settings.config_path)
    return request.app.state.templates.TemplateResponse(
        request, "import.html",
        {"shows": cfg.shows},
    )


@router.get("/config")
def config_page(request: Request):
    path = Path(settings.config_path)
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    return request.app.state.templates.TemplateResponse(
        request, "config.html",
        {"config_content": content, "config_path": str(path)},
    )
