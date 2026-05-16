# Docker - bygg, test och deploy

Projektet distribueras som en **Docker-image** (ingen docker-compose). Lokalt
körs den med `docker run`, på Unraid läggs den till som en container via
Unraids "Add Container"-mall.

## Bygga imagen

```bash
docker build -t kafferepet-dl:latest .
```

(När CI är uppsatt byggs och pushas imagen till `ghcr.io/armandur/kafferepet-dl`.)

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
| `RUN_ONCE` | `false` | `true` = kör en gång och avsluta |
| `RUN_ON_START` | `true` | `false` = hoppa initial körning vid start |
| `SKIP_YTDLP_UPDATE` | `false` | `true` = hoppa `pip install -U yt-dlp` vid start |

**PUID/PGID 99:100** ger filägarskap `nobody:users` - Unraids standard, så Plex
och poddspelaren kan läsa filerna. Behåll dessa värden på Unraid.

## Tre körlägen

Entrypointen väljer läge automatiskt:

1. **Argument givna** - körs med `docker run ... <image> <args>`; argumenten
   skickas rakt till `run.py`, en körning, sedan avslut. Används för test och
   för Unraids "Post Arguments"-fält.
2. **`RUN_ONCE=true`** - en körning av hela flödet, sedan avslut. För Unraid
   User Scripts som startar containern på schema.
3. **Annars** - intern cron enligt `CRON_SCHEDULE`, plus en initial körning
   om `RUN_ON_START=true`.

## Lokal testkörning

Mot fingerade mappar (här under `/mnt/vmworkspace/kafferepet-dl`):

```bash
BASE=/mnt/vmworkspace/kafferepet-dl
docker run --rm \
  -e SKIP_YTDLP_UPDATE=true -e PUID=99 -e PGID=100 \
  -v "$BASE/podcasts/kafferepet:/podcasts/kafferepet" \
  -v "$BASE/podcasts/brandakakor:/podcasts/brandakakor" \
  -v "$BASE/plex/Kafferepet:/plex/Kafferepet" \
  -v "$BASE/plex/Brandakakor:/plex/Brandakakor" \
  -v "$BASE/state:/state" \
  kafferepet-dl:latest --playlist-items 1
```

`--playlist-items 1` begränsar till ett avsnitt per podd. Utelämna argumentet
för en full körning. `config.yaml` måste ligga i `$BASE/state/`.

## Deploy på Unraid

1. Bygg eller hämta imagen.
2. Skapa de fem host-mapparna; lägg `config.yaml` i `/state`-mappen.
3. Skapa de två Plex-biblioteken som typen **Other Videos** (Personal Media).
4. "Add Container" i Unraid:
   - **Repository:** `kafferepet-dl:latest` (eller ghcr.io-sökvägen)
   - **Variables:** `PUID=99`, `PGID=100`, `TZ=Europe/Stockholm`,
     ev. `CRON_SCHEDULE`
   - **Paths:** de fem volymerna enligt tabellen ovan
5. För schemalagd drift: lämna containern igång (intern cron). För
   User-Scripts-drift: sätt `RUN_ONCE=true` och starta containern på schema.

## Uppdatera yt-dlp

Sker automatiskt vid containerstart (`pip install -U yt-dlp`). Starta om
containern för att hämta senaste versionen. Sätt `SKIP_YTDLP_UPDATE=true` för
att hoppa det (snabbare omstart, kör pinnad version).
