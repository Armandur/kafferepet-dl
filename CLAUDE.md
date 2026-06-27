# CLAUDE.md - kafferepet-dl

Kodbasbeskrivning för Claude. Uppdatera denna vid arkitekturändringar.

## Vad projektet är

Tunn Python-wrapper runt yt-dlp + ffmpeg som ersätter flexget för poddarna
Kafferepet och Brända kakor. Hämtar de reklamfria YouTube-versionerna. Ingen
databas, inget webb-UI - yt-dlp:s `--download-archive` är persistensen.

Fullständig kravspec: `kafferepet-downloader-spec.md` (i `/mnt/vmworkspace`).

## Stack

- Python 3.12, stdlib + `yt-dlp`, `mutagen`, `PyYAML` (se `requirements.txt`).
- `ffmpeg` för ljud-/videoextraktion.
- Docker (`python:3.12-slim`), cron i containern, deploy på Unraid.

## Filstruktur

```
config.yaml            huvudkonfig (vid deploy: /state/config.yaml)
run.py                 CLI entrypoint: argparse, orkestrering, exit-kod
downloader/
  config.py            laser + validerar config.yaml -> dataklasser
  ytdlp.py             bygger yt-dlp-argv (audio/video), kor subprocess
  naming.py            titelparsning (regex), sanering, filnamnsbygge
  tagging.py           mutagen-taggning, format-agnostisk (m4a-atomer + ID3)
  postprocess.py       skannar temp-mapp: parsa -> tagga -> dop om -> flytta
  lock.py              fcntl-baserad inter-process lock (delat run.py + webUI)
  episode_index.py     lokal metadata-katalog per show (JSON i /state)
app/                   FastAPI webUI (kor parallellt med cron i containern)
  config.py            settings (env)
  jobs.py              Broadcaster + Runner (en-i-taget, SSE)
  archive.py           lasa/skriva yt-dlp:s arkivfiler
  episodes.py          bygger avsnittslista per podd (spellista + arkiv +
                       lokal metadata + kanalfeed-extras)
  importer.py          manuell import (YouTube, RSS-enclosure, lokal fil)
  main.py              FastAPI-app, lifespan, route-registrering
  routes/api.py        JSON-endpoints + SSE
  routes/pages.py      HTML-vyer (Jinja2)
  templates/           index.html, import.html, base.html
  static/              app.js, style.css
Dockerfile             python:3.12-slim + ffmpeg/cron/gosu/uvicorn
entrypoint.sh          fyra lagen: argument / RUN_ONCE / CRON_ONLY / cron+webUI
```

## Flöde

`run.py` loopar `shows x tracks` ur config. Båda spåren går genom samma
post-proc (`process_track_dir`): parsa numret ur YouTube-titeln, döp om enligt
namnkonventionen.

- **Audio:** yt-dlp -> temp-mapp (`/state/tmp/audio_<slug>`, media + info.json)
  -> post-proc parsar titel, **taggar** (mutagen), flyttar till poddmappen.
  Filnamn: `ÅÅÅÅ-MM-DD - 0000 - Titel.m4a`.
- **Video:** yt-dlp -> mediafilen direkt i Plex-arkivet, `.info.json` till
  `/state/tmp/video_<slug>` -> post-proc parsar titel, döper om filen **på
  plats** (ingen taggning). Videor är stora - mellanlagras aldrig i appdata.
  Filnamn: `ÅÅÅÅ-MM-DD - 0000 - Titel - <videoid>.mp4`.

Temp-mappen (info.json-mappen) är en "att göra"-kö: post-proc körs både före
och efter yt-dlp, så en avbruten körning plockas upp nästa gång. `_safe_move`
gör ett atomiskt `os.replace`, med kopiera-till-`.partial`-fallback över
filsystemsgräns (ljud: `/state` -> `/podcasts`).

## WebUI

FastAPI + Jinja2 + vanilla JS, körs av uvicorn parallellt med cron i samma
container (entrypoint backgrundar cron och `exec`ar uvicorn). Inga portar
behövs internt, port 8000 exponeras utåt.

- **`EpisodesService`** korsar tre datakällor: YouTube-spellistan (via
  `yt-dlp --dump-json --skip-download`), arkivfilerna och `episode_index`
  (lokal metadata-katalog). Plus en valfri **kanalfeed-scan** för videor
  utanför spellistan -- positivt filtrerad på showens `title_regex` så
  Brända kakor-videor inte hamnar under Kafferepet och tvärtom. 5 min
  in-memory-cache; mutationer invaliderar.
- **Lokal metadata-katalog** -- `/state/episodes_<slug>.json` per show.
  Skrivs av `postprocess.py` (YouTube-flöde) och `app.importer` (RSS/lokal).
  Innehåller titel, datum, duration, thumbnail-url, källa och filsökvägar.
  Används för att visa avsnitt utan YouTube-id (bonus-sektionen) och för att
  bevara metadata om YouTube tar bort en video.
- **Server-Sent Events** -- `Broadcaster` med tail-historikbuffer (500 rader)
  så att en nyöppnad flik direkt ser pågående körnings logg.
- **`flock`-baserad inter-process lock** -- `downloader/lock.py`, default
  `/state/run.lock`. Tas av `run.py` vid main() och av webUI:s
  radera/återimport-endpoints. Hindrar att cron och webUI tampas om
  arkivfiler och temp-mappar.
- **`Runner.submit(coro)`** -- en FIFO-kö med en worker som betar av uppgifter
  sekventiellt (en i taget); SSE delas över run.py-subprocesser,
  importer-coroutiner och köändringar.

## Designbeslut

- **En `title_regex` per podd** (config) - numret står på olika plats i de två
  poddarnas titlar. Brända kakor: nummer före titel; Kafferepet: nummer efter.
- **Video har samma namnstruktur som ljud**, plus video-id sist:
  `ÅÅÅÅ-MM-DD - 0000 - Titel - <videoid>.mp4`. Avviker från spec §3/§4b, som
  ville `datum - originaltitel` för video - per användarbeslut 2026-05-16.
  Därför går video genom titelparsning, inte en ren yt-dlp-`outtmpl`.
- **`--no-overwrites` ligger i post-proc, inte på yt-dlp:s temp-anrop** - yt-dlp
  ska kunna återuppta `.part`-filer; skyddet mot att skriva över befintliga
  flexget-filer sker när post-proc kollar `target.exists()`.
- **Padding skiljer sig:** filnamn + Titel-tagg använder 4-siffrig padding
  (`0179`), Track-taggen använder rått nummer (`179`). Se spec B3.
- **Albumartist lämnas osatt** (spec F4).
- **Taggning format-agnostisk** - befintlig backlog är `.mp3`, nya filer `.m4a`;
  taggvärdena ska vara identiska så biblioteket visas enhetligt.
- **`title_template` per podd (valfri, config)** - normalt bygger filnamn/Titel-
  tagg `0000 - Titel` (nollutfyllt nummer). Sätts `title_template` på en show och
  numret parsas, byggs titeldelen i stället ur mallen med platshållarna `{num}`
  (rått nummer, ingen nollutfyllnad) och `{title}` (parsad titel). Sommarkakor
  använder `"Sommarkakor {num} - {title}"` -> `ÅÅÅÅ-MM-DD - Sommarkakor 1 - Colgate-korv.m4a`.
  Filnamn och Titel-tagg delar `naming.build_title_tag`/`build_filename` så texten
  blir identisk (filnamnet saneras, taggen inte). Saknas mallen eller numret
  faller showen tillbaka på standardformatet (bakåtkompatibelt).

## Konfiguration

Allt styrs av `config.yaml`. `defaults` + `shows[]` med `tracks.audio`/`video`.
Filnamnsmönstret är medvetet **kodlåst** (spec F1/F3) - inte config-driven.

## Vanliga ändringar

- **Justera titel-parsning:** ändra `title_regex` för showen i `config.yaml`.
  Verifiera med `run.py --dry-run` innan skarp körning.
- **Lägg till en podd:** nytt block under `shows:` med egen `playlist_id`,
  `title_regex` och fyra distinkta sökvägar. Lägg ev. `channel_url` för
  kanalfeed-sektionen i webUI:t och `title_template` för avvikande namnformat.
- **Aktivera retention:** sätt `retention_days > 0` på ett spår.
- **Lägg till en webUI-route:** ny modul under `app/routes/` eller utöka
  api.py/pages.py och registrera i `main.py`. Statiska resurser i
  `app/static/`, templates i `app/templates/`.

## Verifiering

```bash
.venv/bin/python -c "import run, downloader.config, downloader.ytdlp, \
  downloader.naming, downloader.tagging, downloader.postprocess; print('OK')"
YTDLP_BIN=.venv/bin/yt-dlp .venv/bin/python run.py --config config.yaml --dry-run
```

## Ej i scope (v1.0)

Webb-UI/API, databas, SponsorBlock, notifieringar (hook förberedd i
`run.py:_notify`, se ROADMAP.md).
