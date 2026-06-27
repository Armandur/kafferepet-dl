"""FastAPI-app for kafferepet-dl webUI."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.episodes import EpisodesService
from app.jobs import Broadcaster, Runner
from app.routes import api, config, pages
from app.scheduler import Scheduler

BASE = Path(__file__).parent
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")


@asynccontextmanager
async def lifespan(app: FastAPI):
    broadcaster = Broadcaster()
    app.state.runner = Runner(broadcaster)
    app.state.episodes = EpisodesService()
    app.state.scheduler = Scheduler(app.state.runner)
    app.state.scheduler.start()
    try:
        yield
    finally:
        await app.state.scheduler.stop()


app = FastAPI(title="kafferepet-dl webUI", lifespan=lifespan)
app.state.templates = Jinja2Templates(directory=BASE / "templates")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(pages.router)
app.include_router(api.router, prefix="/api")
app.include_router(config.router, prefix="/api")
