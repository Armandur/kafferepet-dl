"""WebUI-specifika installningar. Lases ur env vid app-start."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings:
    config_path = os.environ.get("CONFIG_PATH",
                                 str(PROJECT_ROOT / "config.yaml"))
    state_dir = Path(os.environ.get("STATE_DIR", "/state"))
    log_history = int(os.environ.get("LOG_HISTORY", "500"))


settings = Settings()
