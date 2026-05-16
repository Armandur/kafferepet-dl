#!/usr/bin/env bash
# Containerns entrypoint. Tre lagen:
#   1. Argument givna  -> kor run.py med dem en gang och avslutar
#   2. RUN_ONCE=true   -> kor run.py --once en gang och avslutar
#   3. annars          -> schemalagd korning via cron
set -euo pipefail

PUID="${PUID:-99}"
PGID="${PGID:-100}"
CONFIG="${CONFIG_PATH:-/state/config.yaml}"
CRON_SCHEDULE="${CRON_SCHEDULE:-0 3 * * *}"

if [ "${SKIP_YTDLP_UPDATE:-false}" != "true" ]; then
    echo "[entrypoint] Uppdaterar yt-dlp till senaste versionen..."
    pip install --no-cache-dir -U yt-dlp \
        || echo "[entrypoint] Varning: kunde inte uppdatera yt-dlp, kor pinnad version"
fi

# Sakerstall att state-mappen finns och ags av ratt anvandare.
mkdir -p /state/tmp
chown -R "$PUID:$PGID" /state 2>/dev/null || true

# Lage 1: extra argument -> skicka rakt till run.py (test, Unraid post-args).
if [ "$#" -gt 0 ]; then
    echo "[entrypoint] Kor run.py med argument: $*"
    exec gosu "$PUID:$PGID" python run.py --config "$CONFIG" "$@"
fi

# Lage 2: engangskorning.
if [ "${RUN_ONCE:-false}" = "true" ]; then
    echo "[entrypoint] RUN_ONCE satt - kor en gang och avslutar"
    exec gosu "$PUID:$PGID" python run.py --config "$CONFIG" --once
fi

# Lage 3: schemalagd korning. Jobbet laggs i /etc/cron.d (har anvandarfalt).
CRON_CMD="cd /app && gosu $PUID:$PGID python run.py --config $CONFIG > /proc/1/fd/1 2>/proc/1/fd/2"
printf '%s root %s\n' "$CRON_SCHEDULE" "$CRON_CMD" > /etc/cron.d/kafferepet-dl
chmod 0644 /etc/cron.d/kafferepet-dl
echo "[entrypoint] Schemalagd korning: $CRON_SCHEDULE"

if [ "${RUN_ON_START:-true}" = "true" ]; then
    echo "[entrypoint] Kor initial korning..."
    gosu "$PUID:$PGID" python run.py --config "$CONFIG" \
        || echo "[entrypoint] Initial korning gav fel - cron fortsatter anda"
fi

echo "[entrypoint] Startar cron i forgrunden..."
exec cron -f
