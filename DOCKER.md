# Docker - bygg, test och deploy

Projektet distribueras som en **Docker-image** (ingen docker-compose). Lokalt
körs den med `docker run`, på Unraid läggs den till som en container via
Unraids "Add Container"-mall.

## Imagen

GitHub Actions bygger och publicerar imagen automatiskt vid varje push till
`main` och vid `v*`-taggar (`.github/workflows/docker-publish.yml`):

```
ghcr.io/armandur/kafferepet-dl:latest        senaste main
ghcr.io/armandur/kafferepet-dl:sha-<sha>     specifik commit
ghcr.io/armandur/kafferepet-dl:vX.Y.Z        vid v-taggar
```

Hämta den:

```bash
docker pull ghcr.io/armandur/kafferepet-dl:latest
```

Ghcr-paketet är privat tills det görs publikt en gång (Package settings ->
Change visibility). Är det privat måste Unraid logga in mot ghcr.io med en
PAT som har `read:packages`.

Bygga lokalt för test:

```bash
docker build -t kafferepet-dl:test .
```

## Volymer

Container-sökvägarna är fasta - koden refererar dem. Host-sidan monteras med `-v`.

| Container-path | Innehåll | Läge |
|---|---|---|
| `/podcasts/kafferepet` | Kafferepets befintliga poddmapp | rw |
| `/podcasts/brandakakor` | Brända kakors poddmapp | rw |
| `/plex/Kafferepet` | Plex-arkiv (Kafferepet) | rw |
| `/plex/Brandakakor` | Plex-arkiv (Brända kakor) | rw |
| `/state` | appdata: `config.yaml` + arkivfiler + temp | rw |

De fyra utdatamapparna ska vara fyra **olika** host-mappar.

## Miljövariabler

| Variabel | Default | Effekt |
|---|---|---|
| `TZ` | `Europe/Stockholm` | tidszon (påverkar cron) |
| `PUID` / `PGID` | `99` / `100` | äganderätt på skapade filer (Unraid: nobody/users) |
| `CRON_SCHEDULE` | `0 3 * * *` | cron-uttryck för schemalagd körning |
| `CONFIG_PATH` | `/state/config.yaml` | sökväg till config i containern |
| `WEBUI_PORT` | `8000` | port som uvicorn lyssnar på |
| `STATE_DIR` | `/state` | basmapp för arkivfiler, lock, metadata-katalog och temp |
| `RUN_LOCK_PATH` | `/state/run.lock` | flock-fil som hindrar samtidiga cron/webUI-körningar |
| `RUN_ONCE` | `false` | `true` = kör en gång och avsluta (utan webUI) |
| `CRON_ONLY` | `false` | `true` = kör cron-daemon utan webUI |
| `RUN_ON_START` | `true` | `false` = hoppa initial körning vid start |
| `SKIP_YTDLP_UPDATE` | `false` | `true` = hoppa `pip install -U yt-dlp` vid start |
| `NTFY_URL` | -- | full URL till en ntfy-topic (notiser vid nya filer / fel) |
| `HA_WEBHOOK_URL` | -- | Home Assistant webhook-URL (POST JSON, samma triggers) |

**PUID/PGID 99:100** ger filägarskap `nobody:users` - Unraids standard, så Plex
och poddspelaren kan läsa filerna. Behåll dessa värden på Unraid.

## Fyra körlägen

Entrypointen väljer läge automatiskt:

1. **Argument givna** - körs med `docker run ... <image> <args>`; argumenten
   skickas rakt till `run.py`, en körning, sedan avslut. Används för test och
   för Unraids "Post Arguments"-fält.
2. **`RUN_ONCE=true`** - en körning av hela flödet, sedan avslut. För Unraid
   User Scripts som startar containern på schema.
3. **`CRON_ONLY=true`** - bara cron-daemon i förgrunden (utan webUI).
4. **Annars** - cron-daemon i bakgrunden + webUI (uvicorn) i förgrunden.
   Standardläget för Unraid-deploy. Exponera port 8000.

## Lokal testkörning

Mot fingerade mappar (här under `/mnt/vmworkspace/kafferepet-dl`):

```bash
BASE=/mnt/vmworkspace/kafferepet-dl
docker run -d --name kafferepet-dl \
  -e SKIP_YTDLP_UPDATE=true -e PUID=99 -e PGID=100 \
  -p 8000:8000 \
  -v "$BASE/podcasts/kafferepet:/podcasts/kafferepet" \
  -v "$BASE/podcasts/brandakakor:/podcasts/brandakakor" \
  -v "$BASE/plex/Kafferepet:/plex/Kafferepet" \
  -v "$BASE/plex/Brandakakor:/plex/Brandakakor" \
  -v "$BASE/state:/state" \
  kafferepet-dl:latest
```

Öppna `http://<host>:8000/` för översiktssidan. Cron-jobbet körs i bakgrunden
inuti containern enligt `CRON_SCHEDULE`. Vill du köra en engångskommandorad
istället: lägg argument efter image-namnet (t.ex. `--playlist-items 1` för
ett avsnitt per podd) -- containern kör då `run.py` med dem och avslutar.

`config.yaml` måste ligga i `$BASE/state/` innan första start.

## Deploy på Unraid

1. Hämta imagen: `docker pull ghcr.io/armandur/kafferepet-dl:latest`.
2. Skapa de fem host-mapparna; lägg `config.yaml` i `/state`-mappen.
3. Skapa de två Plex-biblioteken som typen **Other Videos** (Personal Media).
4. "Add Container" i Unraid:
   - **Repository:** `ghcr.io/armandur/kafferepet-dl:latest`
   - **Network Type:** `bridge`
   - **Port:** host `8000` → container `8000` (webUI)
   - **Variables:** `PUID=99`, `PGID=100`, `TZ=Europe/Stockholm`,
     ev. `CRON_SCHEDULE`
   - **Paths:** de fem volymerna enligt tabellen ovan
5. Standardläget kör cron + webUI samtidigt. För User-Scripts-drift utan
   webUI: sätt `RUN_ONCE=true` och starta containern på schema.

## Uppdatera yt-dlp

Sker automatiskt vid containerstart (`pip install -U yt-dlp`). Starta om
containern för att hämta senaste versionen. Sätt `SKIP_YTDLP_UPDATE=true` för
att hoppa det (snabbare omstart, kör pinnad version).
