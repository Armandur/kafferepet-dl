FROM python:3.12-slim

# ffmpeg: ljud-/videoextraktion. cron: schemalagd korning. gosu: kora som PUID/PGID.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg cron gosu tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY downloader/ ./downloader/
COPY run.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV TZ=Europe/Stockholm \
    CONFIG_PATH=/state/config.yaml

ENTRYPOINT ["/app/entrypoint.sh"]
