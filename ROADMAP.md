# ROADMAP - kafferepet-dl

## v1.0 (klart)

- Config-driven nedladdning av ljud + video per podd.
- Titelparsning per podd via `title_regex`, post-processing med taggning.
- Persistent download-arkiv, idempotent körning (temp-mapp som kö).
- Docker-deploy på Unraid med cron eller RUN_ONCE.

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
