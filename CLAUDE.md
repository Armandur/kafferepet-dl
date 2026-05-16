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
run.py                 entrypoint: argparse, orkestrering, sammanfattning, exit-kod
downloader/
  config.py            laser + validerar config.yaml -> dataklasser
  ytdlp.py             bygger yt-dlp-argv (audio/video), kor subprocess
  naming.py            titelparsning (regex), sanering, filnamnsbygge
  tagging.py           mutagen-taggning, format-agnostisk (m4a-atomer + ID3)
  postprocess.py       skannar temp-mapp: parsa -> tagga -> dop om -> flytta
Dockerfile             python:3.12-slim + ffmpeg/cron/gosu
entrypoint.sh          tre lagen: argument / RUN_ONCE / cron (se DOCKER.md)
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

## Konfiguration

Allt styrs av `config.yaml`. `defaults` + `shows[]` med `tracks.audio`/`video`.
Filnamnsmönstret är medvetet **kodlåst** (spec F1/F3) - inte config-driven.

## Vanliga ändringar

- **Justera titel-parsning:** ändra `title_regex` för showen i `config.yaml`.
  Verifiera med `run.py --dry-run` innan skarp körning.
- **Lägg till en podd:** nytt block under `shows:` med egen `playlist_id`,
  `title_regex` och fyra distinkta sökvägar.
- **Aktivera retention:** sätt `retention_days > 0` på ett spår.

## Verifiering

```bash
.venv/bin/python -c "import run, downloader.config, downloader.ytdlp, \
  downloader.naming, downloader.tagging, downloader.postprocess; print('OK')"
YTDLP_BIN=.venv/bin/yt-dlp .venv/bin/python run.py --config config.yaml --dry-run
```

## Ej i scope (v1.0)

Webb-UI/API, databas, SponsorBlock, notifieringar (hook förberedd i
`run.py:_notify`, se ROADMAP.md).
