#!/usr/bin/env bash
# Containerns entrypoint. Tre lagen:
#   1. Argument givna  -> kor run.py med dem en gang och avslutar
#   2. RUN_ONCE=true   -> kor run.py --once en gang och avslutar
#   3. annars          -> uvicorn (webUI) med inbyggd asyncio-scheduler
set -euo pipefail

PUID="${PUID:-99}"
PGID="${PGID:-100}"
CONFIG="${CONFIG_PATH:-/state/config.yaml}"
WEBUI_PORT="${WEBUI_PORT:-8000}"

if [ "${SKIP_YTDLP_UPDATE:-false}" != "true" ]; then
    echo "[entrypoint] Uppdaterar yt-dlp till senaste versionen..."
    pip install --no-cache-dir -U yt-dlp \
        || echo "[entrypoint] Varning: kunde inte uppdatera yt-dlp, kor pinnad version"
fi

mkdir -p /state/tmp
chown -R "$PUID:$PGID" /state 2>/dev/null || true

# Lage 1: extra argument -> skicka rakt till run.py (test, Unraid post-args).
if [ "$#" -gt 0 ]; then
    echo "[entrypoint] Kor run.py med argument: $*"
    exec gosu "$PUID:$PGID" python run.py --config "$CONFIG" "$@"
fi

# Lage 2: engangskorning, ingen webUI.
if [ "${RUN_ONCE:-false}" = "true" ]; then
    echo "[entrypoint] RUN_ONCE satt - kor en gang och avslutar"
    exec gosu "$PUID:$PGID" python run.py --config "$CONFIG" --once
fi

# Lage 3: webUI med inbyggd scheduler (CRON_SCHEDULE styr).
echo "[entrypoint] Startar webUI pa 0.0.0.0:$WEBUI_PORT (PUID=$PUID PGID=$PGID)..."
echo "[entrypoint] Schemalagd korning hanteras av app.scheduler (CRON_SCHEDULE=${CRON_SCHEDULE:-0 3 * * *})"
exec gosu "$PUID:$PGID" \
    uvicorn app.main:app --host 0.0.0.0 --port "$WEBUI_PORT"
