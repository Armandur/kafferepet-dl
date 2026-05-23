FROM python:3.12-slim

# ffmpeg: ljud-/videoextraktion. cron: schemalagd korning. gosu: kora som PUID/PGID.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg cron gosu tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY downloader/ ./downloader/
COPY app/ ./app/
COPY run.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV TZ=Europe/Stockholm \
    CONFIG_PATH=/state/config.yaml \
    WEBUI_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"WEBUI_PORT\",\"8000\")}/api/health', timeout=3).read()" \
    || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
