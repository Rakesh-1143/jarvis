"""Piece BH: play songs from your own Music folder (offline).

Intent:
  local_music {action: play|shuffle|list|rescan, artist?, album?, song?, query?}
    play     - play matching songs (song, artist, album, or a free query that tries all three)
    shuffle  - shuffle all songs, or only those of the artist/album given
    list     - (info) what songs/albums I have by an artist, or a library summary
    rescan   - rebuild the music index ("update my music library")

How it works:
  - Scans the Music folder + config `music_folders` for mp3/m4a/flac/wav/ogg.
  - Reads tags with `mutagen` if installed; otherwise uses "Artist - Title" file names and the folder as album.
  - Caches the index in `music_index_file` (default ~/.jarvis/music_index.json). Rescans when older than 1 day,
    when the folder list changes, or (once) when nothing matches and the index is a few minutes old.
  - Writes a .m3u8 playlist in the temp folder and opens it with VLC (config `vlc_path` or the usual install
    places) or else the default player. Pause / next / previous use the existing media keys (desktop.media).

Config (all optional):
  music_folders: ["D:/Songs"]               # extra folders (the normal Music folder is always included)
  music_index_file: ~/.jarvis/music_index.json
  vlc_path: "C:/Program Files/VideoLAN/VLC/vlc.exe"
"""
from __future__ import annotations

import difflib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

AUDIO_EXT = {".mp3", ".m4a", ".flac", ".wav", ".ogg"}
DEFAULT_INDEX = "~/.jarvis/music_index.json"
MAX_AGE = 24 * 3600          # rescan when the index is older than 1 day
RETRY_AGE = 5 * 60           # nothing matched: rescan once if the index is older than this
MAX_FILES = 50000
MAX_PLAYLIST = 1000
PLAYLIST_NAME = "jarvis_music.m3u8"
NO_MUSIC = "I couldn't find any songs in your Music folder. Add some, then say update my music library."


# ---------- config ----------

def _config() -> dict:
    try:
        from jarvis.config import load_config
        return load_config() or {}
    except Exception:
        return {}


def _music_dir() -> Path:
    try:
        from .files import _known_folder
        p = _known_folder("music")
        if p:
            return p
    except Exception:
        pass
    return Path.home() / "Music"


def music_folders(cfg: dict | None = None) -> list[Path]:
    """The Music folder + config music_folders, existing ones only, no repeats."""
    cfg = _config() if cfg is None else cfg
    extra = cfg.get("music_folders") or []
    if isinstance(extra, str):
        extra = [extra]
    out: list[Path] = []
    seen: set[str] = set()
    for raw in [_music_dir(), *extra]:
        try:
            p = Path(os.path.expanduser(str(raw)))
            key = os.path.normcase(str(p.resolve()))
        except (OSError, ValueError):
            continue
        if key not in seen and p.is_dir():
            seen.add(key)
            out.append(p)
    return out


def _index_path(cfg: dict | None = None) -> Path:
    cfg = _config() if cfg is None else cfg
    return Path(os.path.expanduser(str(cfg.get("music_index_file") or DEFAULT_INDEX)))


# ---------- tags ----------

def _first(tags, key: str) -> str:
    try:
        v = tags.get(key)
    except Exception:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v or "").strip()


def _track_no(text: str) -> int:
    m = re.match(r"\s*(\d+)", text or "")
    return int(m.group(1)) if m else 0


def _guess_from_name(path: Path) -> dict:
    """No tags: "Artist - Title.mp3" -> artist, title. Album = parent folder name."""
    stem = re.sub(r"^\s*\d{1,3}[\s.\-_]+", "", path.stem)  # "01 - Song" -> "Song"
    artist, title = "", stem
    if " - " in stem:
        artist, title = (s.strip() for s in stem.split(" - ", 1))
    return {"title": title or path.stem, "artist": artist, "album": path.parent.name, "track": 0}


def read_tags(path: Path) -> dict:
    """{title, artist, album, track}. Falls back to the file name when mutagen or tags are missing."""
    guess = _guess_from_name(path)
    try:
        import mutagen  # optional
        f = mutagen.File(str(path), easy=True)
    except Exception:
        f = None
    tags = getattr(f, "tags", None) if f is not None else None
    if not tags:
        return guess
    return {
        "title": _first(tags, "title") or guess["title"],
        "artist": _first(tags, "artist") or _first(tags, "albumartist") or guess["artist"],
        "album": _first(tags, "album") or guess["album"],
        "track": _track_no(_first(tags, "tracknumber")),
    }


# ---------- index ----------

def scan(folders: list[Path]) -> list[dict]:
    tracks: list[dict] = []
    for root in folders:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() not in AUDIO_EXT or name.startswith("."):
                    continue
                tracks.append({"path": str(p), **read_tags(p)})
                if len(tracks) >= MAX_FILES:
                    return tracks
    return tracks


def _folder_keys(folders: list[Path]) -> list[str]:
    return sorted(os.path.normcase(str(f)) for f in folders)


def rebuild(cfg: dict | None = None) -> dict:
    cfg = _config() if cfg is None else cfg
    folders = music_folders(cfg)
    index = {"built": time.time(), "folders": _folder_keys(folders), "tracks": scan(folders)}
    path = _index_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # still usable in memory
    return index


def load_index(cfg: dict | None = None, force: bool = False) -> dict:
    cfg = _config() if cfg is None else cfg
    if not force:
        try:
            data = json.loads(_index_path(cfg).read_text(encoding="utf-8"))
            fresh = time.time() - float(data.get("built") or 0) < MAX_AGE
            same = data.get("folders") == _folder_keys(music_folders(cfg))
            if isinstance(data.get("tracks"), list) and fresh and same:
                return data
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return rebuild(cfg)


# ---------- matching ----------

def _norm(text: str) -> str:
    t = str(text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _clean_query(text: str) -> str:
    t = _norm(text)
    t = re.sub(r"^(the )?(album|song|track|songs|music) ", "", t)
    t = re.sub(r" (album|song|track|songs|music)$", "", t)
    t = re.sub(r"^(some|all) ", "", t)
    return t.strip()


def _matches(field_value: str, query: str) -> bool:
    """Every query word appears in the field ("arijit" matches "Arijit Singh, Shreya Ghoshal")."""
    f = _norm(field_value)
    if not f or not query:
        return False
    if query in f:
        return True
    words = f.split()
    return all(w in words for w in query.split())


def find(tracks: list[dict], field: str, query: str) -> list[dict]:
    q = _clean_query(query)
    if not q:
        return []
    hits = [t for t in tracks if _matches(t.get(field, ""), q)]
    if hits:
        return hits
    # Speech-to-text typos: "arjit sing" -> "arijit singh"
    names = {_norm(t.get(field, "")): None for t in tracks if t.get(field)}
    close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.75)
    if close:
        return [t for t in tracks if _norm(t.get(field, "")) == close[0]]
    return []


def _sorted(tracks: list[dict]) -> list[dict]:
    return sorted(tracks, key=lambda t: (_norm(t.get("album", "")), t.get("track") or 0, _norm(t.get("title", ""))))


def _select(tracks: list[dict], args: dict) -> tuple[list[dict], str]:
    """Pick tracks from args. Returns (tracks, label for the reply). Empty list + label = not found."""
    song = str(args.get("song") or "").strip()
    artist = str(args.get("artist") or "").strip()
    album = str(args.get("album") or "").strip()
    query = str(args.get("query") or "").strip()
    if song:
        hits = find(tracks, "title", song)
        if artist:
            hits = [t for t in hits if _matches(t.get("artist", ""), _clean_query(artist))] or hits
        return hits, song
    if album:
        hits = _sorted(find(tracks, "album", album))
        if artist:
            hits = [t for t in hits if _matches(t.get("artist", ""), _clean_query(artist))] or hits
        return hits, f"the album {hits[0]['album'] if hits else album}"
    if artist:
        return _sorted(find(tracks, "artist", artist)), artist
    if query:
        for field in ("title", "artist", "album"):
            hits = find(tracks, field, query)
            if hits:
                label = hits[0]["title"] if field == "title" and len(hits) == 1 else query
                return (_sorted(hits) if field != "title" else hits), label
        return [], query
    return list(tracks), ""


# ---------- player ----------

def _vlc_path(cfg: dict) -> str | None:
    cand = [cfg.get("vlc_path")]
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            cand.append(os.path.join(base, "VideoLAN", "VLC", "vlc.exe"))
    for c in cand:
        if c and os.path.isfile(os.path.expanduser(str(c))):
            return os.path.expanduser(str(c))
    return shutil.which("vlc")


def write_playlist(tracks: list[dict]) -> Path:
    path = Path(tempfile.gettempdir()) / PLAYLIST_NAME
    lines = ["#EXTM3U"]
    for t in tracks[:MAX_PLAYLIST]:
        name = f"{t.get('artist')} - {t.get('title')}" if t.get("artist") else str(t.get("title") or "")
        lines.append(f"#EXTINF:-1,{name}")
        lines.append(str(t["path"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _startfile(path: str) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only


def _launch(playlist: Path, cfg: dict) -> None:
    vlc = _vlc_path(cfg)
    if vlc:
        # --one-instance: reuse an open VLC window instead of starting a second player.
        subprocess.Popen([vlc, "--one-instance", str(playlist)], close_fds=True)
    else:
        _startfile(str(playlist))


# ---------- actions ----------

def _song_word(n: int) -> str:
    return "1 song" if n == 1 else f"{n} songs"


def _get_hits(cfg: dict, args: dict) -> tuple[list[dict], str, list[dict]]:
    index = load_index(cfg)
    tracks = index.get("tracks") or []
    hits, label = _select(tracks, args)
    if not hits and time.time() - float(index.get("built") or 0) > RETRY_AGE:
        tracks = rebuild(cfg).get("tracks") or []  # maybe the songs were added after the last scan
        hits, label = _select(tracks, args)
    return hits, label, tracks


def play(args: dict, shuffle: bool = False) -> str:
    cfg = _config()
    hits, label, tracks = _get_hits(cfg, args)
    if not tracks:
        return NO_MUSIC
    if not hits:
        return f"I couldn't find {label} in your music."
    hits = list(hits)
    if shuffle:
        random.shuffle(hits)
    try:
        _launch(write_playlist(hits), cfg)
    except OSError:
        return "I couldn't open a music player."
    if shuffle:
        return f"Shuffling {label}." if label else f"Shuffling your music, {_song_word(len(hits))}."
    if len(hits) == 1:
        h = hits[0]
        return f"Playing {h['title']}" + (f" by {h['artist']}." if h.get("artist") else ".")
    return f"Playing {label}, {_song_word(len(hits))}."


def _names(items: list[str], limit: int = 5) -> str:
    shown = items[:limit]
    more = len(items) - len(shown)
    text = ", ".join(shown)
    return text + (f", and {more} more" if more > 0 else "")


def list_music(args: dict) -> str:
    cfg = _config()
    has_filter = any(str(args.get(k) or "").strip() for k in ("song", "artist", "album", "query"))
    if not has_filter:
        tracks = load_index(cfg).get("tracks") or []
        if not tracks:
            return NO_MUSIC
        artists = sorted({t["artist"] for t in tracks if t.get("artist")}, key=str.lower)
        albums = {t["album"] for t in tracks if t.get("album")}
        text = f"You have {_song_word(len(tracks))} from {len(artists)} artists and {len(albums)} albums."
        return text + (f" Artists include {_names(artists)}." if artists else "")
    hits, label, tracks = _get_hits(cfg, args)
    if not tracks:
        return NO_MUSIC
    if not hits:
        return f"I couldn't find {label} in your music."
    titles = list(dict.fromkeys(t["title"] for t in hits))
    albums = list(dict.fromkeys(t["album"] for t in hits if t.get("album")))
    text = f"You have {_song_word(len(hits))} for {label}: {_names(titles)}."
    if str(args.get("artist") or "").strip() and len(albums) > 1:
        text += f" Albums: {_names(albums, 3)}."
    return text


def rescan(args: dict) -> str:
    cfg = _config()
    folders = music_folders(cfg)
    if not folders:
        return "I couldn't find your Music folder."
    n = len(rebuild(cfg).get("tracks") or [])
    return f"Updated your music library. {_song_word(n)} found." if n else NO_MUSIC


def local_music(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "play").lower()
    if action in ("play", "start"):
        return play(args)
    if action in ("shuffle", "random"):
        return play(args, shuffle=True)
    if action in ("list", "what", "find"):
        return list_music(args)
    if action in ("rescan", "update", "refresh", "scan"):
        return rescan(args)
    return "I can play, shuffle, list, or update your music library."


# ---------- wiring ----------

CATALOG: dict[str, dict] = {
    "local_music": {
        "description": ("Music saved on this PC (Music folder, works offline): play a song, artist or album, "
                        "shuffle all or by artist, list what songs I have by an artist, or rescan the library. "
                        "Use this only when the user says 'my music' / 'from my computer' or names a local album."),
        "properties": {
            "action": {"type": "string", "enum": ["play", "shuffle", "list", "rescan"]},
            "artist": {"type": "string"},
            "album": {"type": "string"},
            "song": {"type": "string"},
            "query": {"type": "string", "description": "Free text when unsure whether it is a song, artist or album."},
        },
        "required": ["action"],
    },
}
HANDLERS = {"local_music": local_music}
