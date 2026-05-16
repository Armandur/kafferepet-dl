#!/usr/bin/env python3
"""Kafferepet/Branda kakor downloader - tunn yt-dlp-wrapper.

Loopar over konfigurerade poddar x spar, laddar ner via yt-dlp och
post-processar ljudspar (titelparsning, taggning, omdopning).
"""
import argparse
import logging
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

from downloader import postprocess, ytdlp
from downloader.config import load_config
from downloader.naming import parse_title

log = logging.getLogger("kafferepet-dl")


class Summary:
    """Samlar resultat per korning for slutsammanfattning + exit-kod."""

    def __init__(self):
        self.created = []       # (show, track, path)
        self.errors = []        # (show, track, video_id)
        self.skipped = 0
        self.job_failures = []  # (show, track, meddelande)

    def add_created(self, show, track, path):
        self.created.append((show, track, path))

    def add_error(self, show, track, vid):
        self.errors.append((show, track, vid))

    def add_skip(self):
        self.skipped += 1

    def add_job_failure(self, show, track, msg):
        self.job_failures.append((show, track, msg))

    @property
    def ok(self):
        return not self.job_failures

    def log_report(self):
        log.info("=" * 60)
        log.info("Sammanfattning")
        log.info("  Nya filer: %d", len(self.created))
        for show, track, path in self.created:
            log.info("    [%s/%s] %s", show, track, path)
        if self.skipped:
            log.info("  Hoppade (malfil fanns redan): %d", self.skipped)
        if self.errors:
            log.info("  Avsnitt med fel: %d", len(self.errors))
            for show, track, vid in self.errors:
                log.info("    [%s/%s] video-id %s", show, track, vid)
        if self.job_failures:
            log.error("  Jobbfel: %d", len(self.job_failures))
            for show, track, msg in self.job_failures:
                log.error("    [%s/%s] %s", show, track, msg)
        log.info("=" * 60)


def _slug(name):
    """Poddnamn -> ascii-slug for temp-mapp, t.ex. 'Brända kakor' -> 'brandakakor'."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r'[^a-z0-9]+', '', ascii_name.lower())


def _notify(summary):
    """Hook for notifiering (Home Assistant/ntfy). Loggar bara i v1.0."""
    log.info("notify-hook: %d nya, %d avsnittsfel, %d jobbfel",
             len(summary.created), len(summary.errors), len(summary.job_failures))


def apply_retention(output_dir, days):
    """Raderar filer aldre an N dagar baserat pa mtime (spec 7).

    Aldrig baserat pa arkivfilen - manuellt sparade filer paverkas inte oavsiktligt.
    """
    cutoff = time.time() - days * 86400
    path = Path(output_dir)
    if not path.is_dir():
        return
    for f in path.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            log.info("Retention: raderar %s", f.name)
            f.unlink()


def run_dry(cfg, show_filter):
    """Torrkorning: testar titel-regex mot alla titlar utan nedladdning."""
    total_unmatched = 0
    for show in cfg.shows:
        if show_filter and show.name != show_filter:
            continue
        log.info("--- Torrkorning: %s ---", show.name)
        for vid, title in ytdlp.flat_playlist(show.playlist_id):
            num, clean = parse_title(title, show.title_regex)
            if num is None:
                total_unmatched += 1
                log.warning("  EJ MATCH: %r (%s)", title, vid)
            else:
                log.info("  OK  num=%s  titel=%r", num, clean)
    log.info("Torrkorning klar: %d titlar utan parsbart nummer", total_unmatched)
    return total_unmatched


def process_show(show, defaults, args, summary):
    """Kor audio- och/eller video-spar for en podd."""
    for kind in ("audio", "video"):
        if args.track and args.track != kind:
            continue
        track = getattr(show, kind)
        if track is None or not track.enabled:
            continue
        try:
            # info.json hamnar alltid i en temp-mapp under tmp_root.
            info_dir = os.path.join(defaults["tmp_root"],
                                    f"{kind}_{_slug(show.name)}")
            os.makedirs(info_dir, exist_ok=True)
            # Ljud post-processas i temp-mappen; video doper om i Plex-arkivet.
            media_dir = info_dir if kind == "audio" else track.output_dir
            # Tom ev. orphans fran en tidigare avbruten korning forst.
            postprocess.process_track_dir(info_dir, media_dir, show, track,
                                          defaults, summary)
            if kind == "audio":
                failed = ytdlp.run_audio(show, track, info_dir, defaults,
                                         args.playlist_items)
            else:
                failed = ytdlp.run_video(show, track, info_dir, defaults,
                                         args.playlist_items)
            postprocess.process_track_dir(info_dir, media_dir, show, track,
                                          defaults, summary)
            for vid in failed:
                summary.add_error(show.name, kind, vid)
            if track.retention_days > 0:
                apply_retention(track.output_dir, track.retention_days)
        except Exception as exc:
            log.error("Jobb %s/%s misslyckades: %s", show.name, kind, exc)
            summary.add_job_failure(show.name, kind, str(exc))


def main():
    parser = argparse.ArgumentParser(description="Kafferepet/Branda kakor downloader")
    parser.add_argument("--config",
                        default=os.environ.get("CONFIG_PATH", "/state/config.yaml"))
    parser.add_argument("--show", help="kor bara denna podd (exakt namn)")
    parser.add_argument("--track", choices=["audio", "video"],
                        help="kor bara detta spar")
    parser.add_argument("--playlist-items",
                        help="yt-dlp --playlist-items, t.ex. '1' eller '1-3'")
    parser.add_argument("--dry-run", action="store_true",
                        help="testa titel-regex mot spellistorna, ladda inte ner")
    parser.add_argument("--once", action="store_true",
                        help="informativ flagga; varje korning ar redan en engangskorning")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    cfg = load_config(args.config)

    if args.dry_run:
        unmatched = run_dry(cfg, args.show)
        sys.exit(0 if unmatched == 0 else 1)

    summary = Summary()
    for show in cfg.shows:
        if args.show and show.name != args.show:
            continue
        log.info("### Podd: %s ###", show.name)
        process_show(show, cfg.defaults, args, summary)

    summary.log_report()
    _notify(summary)
    sys.exit(0 if summary.ok else 1)


if __name__ == "__main__":
    main()
