# kafferepet-dl

Tunn yt-dlp-wrapper som ersätter flexget för poddarna **Kafferepet** och
**Brända kakor**. Hämtar de reklam-/musikfria YouTube-versionerna: ljudspår till
de befintliga poddmapparna, videospår till separata Plex-arkiv.

Källan är två YouTube-spellistor (en per podd). Ingen databas, inget webb-UI -
yt-dlp:s `--download-archive` håller reda på vad som redan hämtats.

## Hur det fungerar

- **Ljud:** yt-dlp laddar ner till en temp-mapp, ett post-processing-steg
  parsar avsnittsnummret ur YouTube-titeln, taggar filen (mutagen) och döper om
  den till `ÅÅÅÅ-MM-DD - 0000 - Titel.m4a`. Temp-mappen fungerar som en kö -
  en avbruten körning tas upp nästa gång (idempotent).
- **Video:** yt-dlp laddar ner direkt till Plex-arkivet, ingen omdöpning.

Titelnumret står på olika plats i de två poddarna, därför en `title_regex` per
podd i `config.yaml`.

## Köra lokalt

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Torrkorning - testa titel-regexarna mot spellistorna utan att ladda ner:
YTDLP_BIN=.venv/bin/yt-dlp .venv/bin/python run.py --config config.yaml --dry-run

# Skarp korning av ett enda avsnitt per podd (test):
YTDLP_BIN=.venv/bin/yt-dlp .venv/bin/python run.py --config config.yaml \
  --playlist-items 1

# Full korning:
YTDLP_BIN=.venv/bin/yt-dlp .venv/bin/python run.py --config config.yaml
```

Lokalt pekar `config.yaml`-sökvägarna på container-interna paths (`/podcasts`,
`/plex`, `/state`). Ändra dem till lokala mappar för test, eller använd
`--show`/`--track` för att begränsa körningen.

### CLI-flaggor

| Flagga | Effekt |
|---|---|
| `--config PATH` | sökväg till config.yaml (default `/state/config.yaml`) |
| `--show NAMN` | kör bara denna podd |
| `--track audio\|video` | kör bara detta spår |
| `--playlist-items SPEC` | yt-dlp `--playlist-items`, t.ex. `1` eller `1-3` |
| `--dry-run` | testa titel-regex, ladda inte ner (exit 1 om någon titel inte matchar) |

## Deploy

Docker-container på Unraid, schemalagd via cron. Se [DOCKER.md](DOCKER.md).

## Dokumentation

- [CLAUDE.md](CLAUDE.md) - kodbasbeskrivning
- [DOCKER.md](DOCKER.md) - bygg och deploy
- [ROADMAP.md](ROADMAP.md) - planerade funktioner
- Specen: `kafferepet-downloader-spec.md` (i `/mnt/vmworkspace`)
