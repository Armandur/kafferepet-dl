"""Titelparsning, sanering och filnamnsbygge for ljudspar."""
import re

# Tecken som inte tillats i filnamn pa vanliga filsystem. Tas bort helt
# (anvandarbeslut) - behalls daremot i metadata-taggar.
_FORBIDDEN = '/\\:*?"<>|'
_STRIP_TABLE = str.maketrans({c: None for c in _FORBIDDEN})


def collapse_ws(text):
    """Kollapsar all whitespace till enkla mellanslag och trimmar."""
    return re.sub(r'\s+', ' ', text, flags=re.UNICODE).strip()


def parse_title(raw_title, title_regex):
    """Parsar en YouTube-titel mot showens regex.

    Returnerar (num_raw, clean_title). num_raw ar None om titeln saknar
    parsbart nummer - clean_title ar da hela den trimmade titeln.
    """
    match = re.match(title_regex, raw_title, re.UNICODE)
    if not match:
        return None, collapse_ws(raw_title)
    groups = match.groupdict()
    num_raw = groups.get("num")
    title = collapse_ws(groups.get("title") or raw_title)
    return num_raw, title


def sanitize(text):
    """Tar bort otillatna filnamnstecken och normaliserar whitespace."""
    return collapse_ws(text.translate(_STRIP_TABLE))


def iso_date(upload_date):
    """yt-dlp:s YYYYMMDD -> YYYY-MM-DD."""
    if not upload_date or len(upload_date) != 8:
        return upload_date or ""
    return f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"


def build_filename(upload_date, num_raw, clean_title, ext, padding,
                   missing_mode, suffix=None):
    """Bygger slutligt filnamn: 'YYYY-MM-DD - 0000 - Titel.ext'.

    Nar num_raw saknas styr missing_mode nummerdelen (spec F2):
      omit        -> ingen nummerdel
      placeholder -> nollutfyllt platshallarnummer
    suffix: om satt laggs det till sist med ' - ' (video far sitt video-id har).
    Skiljetecknet ar alltid ' - ' (spec F1); kalltitelns tankstreck normaliseras.
    """
    date = iso_date(upload_date)
    safe_title = sanitize(clean_title)
    ext = ext.lstrip(".")
    if num_raw is None:
        if missing_mode == "placeholder":
            stem = f"{date} - {'0' * padding} - {safe_title}"
        else:  # omit
            stem = f"{date} - {safe_title}"
    else:
        stem = f"{date} - {num_raw.zfill(padding)} - {safe_title}"
    if suffix:
        stem = f"{stem} - {suffix}"
    return f"{stem}.{ext}"
