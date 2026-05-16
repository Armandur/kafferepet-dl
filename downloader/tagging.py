"""Format-agnostisk metadata-taggning (m4a-atomer + ID3) via mutagen.

Taggvardena ar identiska oavsett container sa poddspelare/Plex visar gammalt
(.mp3) och nytt (.m4a) enhetligt. Albumartist lamnas avsiktligt osatt (spec F4).
Omslaget rors inte - det baddas in av yt-dlp --embed-thumbnail.
"""
import logging

from mutagen.id3 import (COMM, ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK,
                         ID3NoHeaderError)
from mutagen.mp4 import MP4

log = logging.getLogger(__name__)


def tag_file(path, *, title, album, artist, genre, track_raw, date_iso, comment):
    """Satter taggar pa en ljudfil. Stodjer .m4a (MP4-atomer) och .mp3 (ID3)."""
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "m4a":
        _tag_mp4(path, title, album, artist, genre, track_raw, date_iso, comment)
    elif ext == "mp3":
        _tag_mp3(path, title, album, artist, genre, track_raw, date_iso, comment)
    else:
        raise ValueError(f"tagging: ostott filformat '{ext}'")


def _tag_mp4(path, title, album, artist, genre, track_raw, date_iso, comment):
    f = MP4(path)
    f["\xa9nam"] = [title]
    f["\xa9alb"] = [album]
    f["\xa9ART"] = [artist]
    f["\xa9gen"] = [genre]
    f["\xa9day"] = [date_iso]
    f["\xa9cmt"] = [comment]
    if track_raw is not None:
        f["trkn"] = [(int(track_raw), 0)]
    else:
        f.pop("trkn", None)
    f.pop("aART", None)  # albumartist: avsiktligt tom (spec F4)
    f.save()


def _tag_mp3(path, title, album, artist, genre, track_raw, date_iso, comment):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TIT2", [TIT2(encoding=3, text=[title])])
    tags.setall("TALB", [TALB(encoding=3, text=[album])])
    tags.setall("TPE1", [TPE1(encoding=3, text=[artist])])
    tags.setall("TCON", [TCON(encoding=3, text=[genre])])
    tags.setall("TDRC", [TDRC(encoding=3, text=[date_iso])])
    tags.delall("COMM")
    tags.add(COMM(encoding=3, lang="swe", desc="", text=[comment]))
    tags.delall("TPE2")  # albumartist: avsiktligt tom (spec F4)
    if track_raw is not None:
        tags.setall("TRCK", [TRCK(encoding=3, text=[str(int(track_raw))])])
    else:
        tags.delall("TRCK")
    tags.save(path, v2_version=4)
