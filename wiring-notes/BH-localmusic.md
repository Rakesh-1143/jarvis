# Wiring notes: piece BH (localmusic.py)

Merge: `from .localmusic import CATALOG as CBH, HANDLERS as HBH`, then update catalog CATALOG and _HANDLERS.
One intent: `local_music {action: play|shuffle|list|rescan, artist?, album?, song?, query?}`.
`list` is info. No risky actions. No main.py hooks.

requirements.txt: add `mutagen` (reads song tags). Optional: without it, tags come from
"Artist - Title.mp3" file names and the folder name as album.

brain.py: add `local_music` to UNTRUSTED_INFO (song tags come from downloaded files and could hold any text).
Not needed in GUARDED_ACTIONS (only opens a player with local files).

Optional config (works without it):
```yaml
music_folders: ["D:/Songs"]                 # extra folders; the normal Music folder is always scanned
music_index_file: ~/.jarvis/music_index.json
vlc_path: "C:/Program Files/VideoLAN/VLC/vlc.exe"   # else default VLC places, else default player
```

## NLU phrases -> args
| Say | Args |
|---|---|
| "play Arijit Singh from my music", "play songs by X from my computer" | {action: play, artist: "Arijit Singh"} |
| "play the album Aashiqui 2 (from my music)" | {action: play, album: "Aashiqui 2"} |
| "play the song Tum Hi Ho from my music", "play my song X" | {action: play, song: "Tum Hi Ho"} |
| "play X from my music" (unclear) | {action: play, query: X} (tries title, artist, album) |
| "play my music", "play music from my computer" | {action: play} (whole library) |
| "shuffle my music", "shuffle my songs" | {action: shuffle} |
| "shuffle Arijit Singh from my music" | {action: shuffle, artist: ...} |
| "what songs do I have by X", "which albums do I have by X" | {action: list, artist: X} |
| "what's in my music library", "how many songs do I have" | {action: list} |
| "update/rescan/refresh my music library" | {action: rescan} |

Notes:
- Must be matched BEFORE the generic "play X" (YouTube `play` / spotify) rule, but ONLY when the phrase says
  "my music", "my songs", "from my computer/PC/laptop", "local music", or "the album" + library words.
  A plain "play Arijit Singh" stays with the existing YouTube/Spotify rule.
- "shuffle my music" is new; "shuffle" alone may belong to spotify. Keep "my music/songs" required.
- Pause / next / previous / stop stay with `media` (media keys work in VLC and the default player).
- Index rescans itself when older than 1 day, when folders change, or once when nothing matches and it is >5 min old.
- Playlist: `%TEMP%\jarvis_music.m3u8` (UTF-8 so Hindi/accented names work). Max 1000 songs.
- VLC is started with `--one-instance` so a second request should reuse the open window. Not tested on real
  Windows (check it replaces the playlist rather than adding to it).
