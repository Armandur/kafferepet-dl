"""Las/skriv yt-dlp arkivfiler. Format: 'youtube <id>' per rad."""
from pathlib import Path


def read_ids(path) -> set[str]:
    """Returnerar set av video-id i arkivfilen. Tom om filen saknas."""
    p = Path(path)
    if not p.is_file():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            out.add(parts[-1])
    return out


def remove_id(path, video_id) -> bool:
    """Tar bort raden(/-erna) med video_id. Returnerar True om något togs bort."""
    p = Path(path)
    if not p.is_file():
        return False
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept = [ln for ln in lines if ln.strip().split()[-1] != video_id]
    if len(kept) == len(lines):
        return False
    p.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    return True
