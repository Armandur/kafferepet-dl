"""HTML-vyer."""
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
