# ROADMAP - kafferepet-dl

## v1.0 (klart)

- Config-driven nedladdning av ljud + video per podd.
- Titelparsning per podd via `title_regex`, post-processing med taggning.
- Persistent download-arkiv, idempotent körning (temp-mapp som kö).
- Docker-deploy på Unraid med cron eller RUN_ONCE.

## v1.2 (klart, feat-v1.2-branchen)

- **Audio-radera med filspårning** via metadata-katalogens audio_path.
- **Health-check** (`GET /api/health`) + Dockerfile HEALTHCHECK.
- **Sökfält + statusfilter** i avsnittslistan (titel-sök, status: alla/
  imported/missing/archived_no_file).
- **Disk-användning per podd** visas i show-headern (ljud + video bytes).
- **Notifieringar** vid nya filer / fel via NTFY_URL och/eller
  HA_WEBHOOK_URL.
- **Körningshistorik** -- senaste 50 körningar i `/state/runs/`, lista
  + detaljer på dashboard.
- **Audio-transcript** -- YouTube-undertexter hämtas vid post-proc,
  visas i modal via knapp på imported audio.

## v1.1 (klart, feat-webui-branchen)

- WebUI (FastAPI + Jinja2 + vanilla JS) som körs parallellt med cron.
- Dashboard med avsnittslista per podd: thumbnails, status, datum, speltid,
  predicted filnamn, knappar för importera/återimport/radera.
- Sektioner per podd: spellistans avsnitt, bonus-specialavsnitt (RSS/lokal),
  övriga kanalvideor utanför spellistan (kräver `channel_url` i config).
- Sidnumrering vid >24 avsnitt.
- Manuell import med review-flow: YouTube-URL, RSS-enclosure, lokal filsökväg.
- Live-logg via SSE.
- Lokal metadata-katalog per show (`/state/episodes_<slug>.json`).
- flock-baserat inter-process lock kring run.py och webUI-mutationer.

## Planerat / valfritt

- **Notifieringshook** - `run.py:_notify()` är förberedd men loggar bara.
  Koppla till Home Assistant-webhook eller ntfy när nya avsnitt hämtats eller
  fel uppstått. (Spec §10b steg 6.)
- **Cookies-stöd** - om YouTube börjar kräva inloggning: montera en cookie-fil
  och skicka `--cookies` till yt-dlp. Implementeras inte aktivt förrän det
  behövs. (Spec §8.)

## Uppskjutet / medvetet utelämnat

- Webb-UI / API - overkill för detta projekt.
- Databas - `--download-archive` räcker.
- SponsorBlock - YouTube-källan är redan reklam-/musikfri.
