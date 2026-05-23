"""Bygger och kor yt-dlp-anrop for ljud- och videoprofiler."""
import logging
import os
import re
import subprocess

log = logging.getLogger(__name__)

# yt-dlp pa PATH i containern; YTDLP_BIN later lokal venv pekas ut vid test.
_YTDLP = os.environ.get("YTDLP_BIN", "yt-dlp")
_ID_RE = re.compile(r'ERROR:.*?([A-Za-z0-9_-]{11})')
_PLAYLIST_URL = "https://www.youtube.com/playlist?list={}"


def _common_args(defaults, archive, playlist_items):
    args = [
        "--download-archive", archive,
        "--sleep-requests", str(defaults["sleep_requests"]),
        "--concurrent-fragments", str(defaults["concurrent_fragments"]),
        "--ignore-errors",
    ]
    if defaults.get("dateafter"):
        args += ["--dateafter", str(defaults["dateafter"])]
    if playlist_items:
        args += ["--playlist-items", str(playlist_items)]
    return args


def run_audio(show, track, tmp_dir, defaults, playlist_items, url=None):
    """Laddar ner ljud till tmp_dir med temporart id-namn. Returnerar fel-id.

    url overridar konfigurerad spellista - anvands av webUI:s manuella import
    av enskild YouTube-video eller annan spellista.

    Inget --no-overwrites: yt-dlp ska kunna ateruppta avbrutna .part-filer.
    Skyddet mot att skriva over befintliga filer ligger i post-proc-steget.
    """
    args = [
        _YTDLP,
        "--extract-audio",
        "--audio-format", defaults["audio_format"],
        "--audio-quality", str(defaults["audio_quality"]),
        "--embed-metadata", "--embed-thumbnail",
        "--write-info-json", "--no-write-playlist-metafiles",
        "--paths", f"home:{tmp_dir}",
        "--output", "%(id)s.%(ext)s",
    ]
    args += _common_args(defaults, track.archive, playlist_items)
    args.append(url or _PLAYLIST_URL.format(show.playlist_id))
    return _run(args, f"{show.name}/audio")


def run_video(show, track, info_dir, defaults, playlist_items, url=None):
    """Laddar ner video till track.output_dir med temporart id-namn.

    url overridar konfigurerad spellista - anvands av webUI:s manuella import.

    Mediafilen gar direkt till Plex-arkivet (videor ar stora - undvik att
    mellanlagra dem i appdata). Bara .info.json routas till info_dir utanfor
    biblioteket; post-proc parsar titeln darifran och doper om filen pa plats.
    """
    args = [
        _YTDLP,
        "--format", defaults["video_format"],
        "--merge-output-format", defaults["video_container"],
        "--embed-metadata", "--embed-thumbnail",
        "--embed-subs", "--sub-langs", "sv,en",
        "--write-info-json", "--no-write-playlist-metafiles",
        "--paths", f"home:{track.output_dir}",
        "--paths", f"infojson:{info_dir}",
        "--output", "%(id)s.%(ext)s",
    ]
    args += _common_args(defaults, track.archive, playlist_items)
    args.append(url or _PLAYLIST_URL.format(show.playlist_id))
    return _run(args, f"{show.name}/video")


def flat_playlist(playlist_id):
    """Returnerar [(id, title), ...] utan att ladda ner (for torrkorning)."""
    args = [_YTDLP, "--flat-playlist", "--print", "%(id)s\t%(title)s",
            _PLAYLIST_URL.format(playlist_id)]
    out = subprocess.run(args, capture_output=True, text=True, check=False)
    rows = []
    for line in out.stdout.splitlines():
        if "\t" in line:
            vid, title = line.split("\t", 1)
            rows.append((vid, title))
    return rows


def _run(args, label):
    """Kor yt-dlp, strommar output till loggen, returnerar set av fel-id.

    Per-avsnitt-fel (ERROR-rader) far inte stoppa korningen - de samlas och
    returneras. Bara ett hart fel utan identifierat avsnitt hojer undantag.
    """
    log.info("Kor yt-dlp: %s", label)
    failed = set()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        log.info("[yt-dlp %s] %s", label, line)
        if line.startswith("ERROR:"):
            m = _ID_RE.search(line)
            if m:
                failed.add(m.group(1))
    code = proc.wait()
    if code != 0 and not failed:
        raise RuntimeError(f"yt-dlp misslyckades ({label}), exit {code}")
    if code != 0:
        log.warning("yt-dlp exit %d for %s (%d avsnitt med fel)",
                    code, label, len(failed))
    return failed
