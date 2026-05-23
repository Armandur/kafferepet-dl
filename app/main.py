"""FastAPI-app for kafferepet-dl webUI."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.jobs import Broadcaster, Runner
from app.routes import api, pages

BASE = Path(__file__).parent
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")


@asynccontextmanager
async def lifespan(app: FastAPI):
    broadcaster = Broadcaster()
    app.state.runner = Runner(broadcaster)
    yield


app = FastAPI(title="kafferepet-dl webUI", lifespan=lifespan)
app.state.templates = Jinja2Templates(directory=BASE / "templates")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(pages.router)
app.include_router(api.router, prefix="/api")
