"""Hamtar YouTube-undertexter via yt-dlp.

Kallas fran postprocess efter en lyckad ljudimport. VTT sparas i en
transcripts-mapp under /state och vagen registreras i episode_index sa
webUI:n kan visa texten.
"""
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_YTDLP = os.environ.get("YTDLP_BIN", "yt-dlp")
_URL_TPL = "https://www.youtube.com/watch?v={}"


def fetch_subs(video_id, dest_dir, langs="sv,sv-orig", timeout=60) -> Path | None:
    """Returnerar Path till en VTT-fil om YouTube har sv-undertexter, annars None.

    Falla tillbaka pa auto-genererade om manuella saknas. Ar tyst pa misslyckande
    (det ar vanligt att ett enskilt avsnitt saknar subs).
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(dest / "%(id)s.%(ext)s")
    args = [
        _YTDLP, "--skip-download",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", langs,
        "--convert-subs", "vtt",
        "--no-warnings",
        "-o", out_tmpl,
        _URL_TPL.format(video_id),
    ]
    try:
        subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        log.warning("transcripts: timeout for %s", video_id)
        return None
    for f in dest.glob(f"{video_id}*.vtt"):
        if f.is_file() and f.stat().st_size > 0:
            return f
    return None
