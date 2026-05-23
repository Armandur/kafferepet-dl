#!/usr/bin/env bash
# Containerns entrypoint. Fyra lagen:
#   1. Argument givna  -> kor run.py med dem en gang och avslutar (test, CLI-style)
#   2. RUN_ONCE=true   -> kor run.py --once en gang och avslutar (User Scripts)
#   3. CRON_ONLY=true  -> kor bara cron-daemon (utan webUI), kvar i forgrunden
#   4. annars          -> cron i bakgrunden + uvicorn (webUI) i forgrunden
set -euo pipefail

PUID="${PUID:-99}"
PGID="${PGID:-100}"
CONFIG="${CONFIG_PATH:-/state/config.yaml}"
CRON_SCHEDULE="${CRON_SCHEDULE:-0 3 * * *}"
WEBUI_PORT="${WEBUI_PORT:-8000}"

if [ "${SKIP_YTDLP_UPDATE:-false}" != "true" ]; then
    echo "[entrypoint] Uppdaterar yt-dlp till senaste versionen..."
    pip install --no-cache-dir -U yt-dlp \
        || echo "[entrypoint] Varning: kunde inte uppdatera yt-dlp, kor pinnad version"
fi

# Sakerstall att state-mappen finns och ags av ratt anvandare.
mkdir -p /state/tmp
chown -R "$PUID:$PGID" /state 2>/dev/null || true

# Lage 1: extra argument -> skicka rakt till run.py.
if [ "$#" -gt 0 ]; then
    echo "[entrypoint] Kor run.py med argument: $*"
    exec gosu "$PUID:$PGID" python run.py --config "$CONFIG" "$@"
fi

# Lage 2: engangskorning, ingen webUI.
if [ "${RUN_ONCE:-false}" = "true" ]; then
    echo "[entrypoint] RUN_ONCE satt - kor en gang och avslutar"
    exec gosu "$PUID:$PGID" python run.py --config "$CONFIG" --once
fi

# Lage 3 & 4: schemalagd korning. Cron-jobbet laggs i /etc/cron.d.
CRON_CMD="cd /app && gosu $PUID:$PGID python run.py --config $CONFIG > /proc/1/fd/1 2>/proc/1/fd/2"
printf '%s root %s\n' "$CRON_SCHEDULE" "$CRON_CMD" > /etc/cron.d/kafferepet-dl
chmod 0644 /etc/cron.d/kafferepet-dl
echo "[entrypoint] Schemalagd korning: $CRON_SCHEDULE"

if [ "${CRON_ONLY:-false}" = "true" ]; then
    echo "[entrypoint] CRON_ONLY satt - startar cron i forgrunden utan webUI"
    exec cron -f
fi

# Lage 4: cron-daemon (bakgrund) + uvicorn (forgrund).
echo "[entrypoint] Startar cron-daemon i bakgrunden..."
cron
echo "[entrypoint] Startar webUI pa 0.0.0.0:$WEBUI_PORT (PUID=$PUID PGID=$PGID)..."
exec gosu "$PUID:$PGID" \
    uvicorn app.main:app --host 0.0.0.0 --port "$WEBUI_PORT"
