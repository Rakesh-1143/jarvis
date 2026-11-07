# Wiring notes: piece Y (spotify.py)

Merge: `from .spotify import CATALOG as CY, HANDLERS as HY`, then update catalog CATALOG and _HANDLERS.
One intent: `spotify {action, query?, kind?, playlist?, state?}`. Not info (replies are spoken). No risky actions. No main.py hooks.
Package: `spotipy>=2.24` (already appended to requirements.txt). Imported lazily, only when a client_id is set.

## Config (add to config.yaml, all optional)
```yaml
spotify:
  client_id: ""        # or env SPOTIPY_CLIENT_ID. Empty = no-keys mode (opens Spotify search only)
  client_secret: ""    # optional, or env SPOTIPY_CLIENT_SECRET. Empty = PKCE login (nothing secret stored)
  redirect_uri: "http://127.0.0.1:8888/callback"   # must match the app in developer.spotify.com
  token_cache: "~/.jarvis/spotify_token.json"
  device: ""           # part of a device name to prefer, e.g. "laptop". Empty = active device, then this PC
```
README: make an app at https://developer.spotify.com/dashboard, add the redirect URI above, copy the Client ID.
First Spotify command opens the browser to log in once. Play/shuffle/repeat need Spotify Premium.

## NLU phrases -> args (only when the user says "spotify", or "like this song" / "add this to my X playlist")
| Say | Args |
|---|---|
| "play shape of you on spotify", "spotify play believer" | {action: play, query: "shape of you"} |
| "play my workout playlist on spotify", "play playlist chill vibes on spotify" | {action: play, query: "my workout playlist"} (module finds kind) |
| "play songs by arijit singh on spotify" | {action: play, query: "songs by arijit singh"} |
| "play my liked songs" | {action: play, query: "my liked songs"} |
| "open spotify and play X" / "play spotify" | {action: play, query: X} / {action: play} |
| "like this song", "save this song", "add this song to my liked songs" | {action: like} |
| "add this song to my gym playlist", "add this to gym playlist" | {action: add_to_playlist, playlist: "gym"} |
| "shuffle on" / "turn off shuffle" (spotify) | {action: shuffle, state: on/off} |
| "repeat this song" / "repeat the playlist" / "repeat off" | {action: repeat, state: track/playlist/off} |
| "what's playing on spotify", "what song is this on spotify" | {action: now_playing} |

Notes:
- Do NOT steal plain "play X" (no "spotify"): that stays `play` (YouTube). Optional: config `music_app: spotify` could
  route plain "play X" here; not built.
- Pause / next / previous stay on the `media` intent. Plain "what's playing" stays on `audio.now_playing`.
- "spotify" alone or "open spotify" stays `open_app`.
- Query cleaning ("the playlist X", "X playlist", "songs by X", "on spotify", Spotify links) is done inside the module,
  so NLU can pass the raw words after "play".
- Live Spotify API was NOT tested (sandbox has no network; spotipy faked). Verify on Windows with a real account.
