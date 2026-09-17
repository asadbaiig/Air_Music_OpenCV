# Air Music

A local webcam remote for Spotify Premium, with a desktop Now Playing screen.

## Library and player layout

Browse your playlists in the left sidebar, select one to see songs, and click a
song to play it. The bottom playback bar remains visible while you browse.
Use the mouse wheel over the library or song list to scroll. Back/More buttons
load another page when there are more than 50 playlists or songs.

Reconnect Spotify after updating to grant `playlist-read-private` and
`playlist-read-collaborative` access. Use Refresh to reload your library. Some
playlists may be restricted by Spotify's API access rules; loading errors appear
in the song panel. Unavailable/local tracks are shown but cannot be played here.
Playlist selection alone does not start playback. Clicking a song starts it in
its playlist context, so working next/previous controls continue through it.

The right camera panel displays gesture status and a hold-progress indicator.
The swipe and volume gesture logic is unchanged by this layout update. Demo mode
includes clearly labeled sample playlists/songs; normal mode displays Spotify data.

The interface is DPI-aware on Windows and rerenders at the window's current size.
Text and controls use supersampling for smoother edges; camera and artwork scaling
use Lanczos filtering. Restart the app after updating to enable the DPI fix.

## Start

Install with Python 3.11, then close Windows Camera before launching:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item spotify_config.example.json spotify_config.json
# Edit spotify_config.json with your own Client ID before connecting.
.\.venv\Scripts\python.exe air_music.py
```

Click **Connect Spotify**, complete the browser login, and return to Air Music.
Open Spotify on your preferred device and start a song there first. Air Music
controls that active device; it does not stream music itself. Click **Enable
gestures** when ready. Click the album artwork to open the current track in Spotify.

## Spotify developer setup

1. Create a Web API app at https://developer.spotify.com/dashboard.
2. Register exactly `http://127.0.0.1:8888/callback` as a Redirect URI.
3. Put the Client ID in `spotify_config.json`, using the example file as a template.
   Alternatively, set `SPOTIFY_CLIENT_ID` or pass `--client-id`.
4. If another account is testing, add it to the app's permitted users as required
   by Spotify's development-mode settings. Use an account with Premium.

Your local spotify_config.json is excluded from Git. No client secret is used.
Browser sign-in uses Authorization Code with PKCE and checks OAuth
state. Tokens stay in memory, are refreshed during the session, and are not saved.
Sign in again after restarting. The login callback listens only on 127.0.0.1:8888
and stops after success, cancellation, or a three-minute timeout.

## Gestures

Keep one hand facing the camera. The preview is mirrored.

| Gesture | Action |
| --- | --- |
| Hold index + middle fingers up (V sign) | Increase volume by 5 points |
| Hold only index finger up | Decrease volume by 5 points |
| Swipe an open palm left | Next track |
| Swipe an open palm right | Previous track |
| Hold an open palm still for 0.8 seconds | Pause |
| Hold thumbs-up for 0.6 seconds | Resume |

Pause/resume fire once until you change pose. Swipe an open hand across roughly
one sixth of the preview within 0.9 seconds. Slight diagonal motion and a briefly
missed finger are tolerated. After each swipe, close your hand briefly (or lower
it out of view) to reset. Swipes also have a 1.2-second cooldown.
Hold a volume pose for 0.6 seconds to start; it repeats at most once every 0.8
seconds. Fold your other fingers. Lower your hand or change pose to stop generating
steps (an already-sent request may still finish). No pinching or hand movement is
needed. Each step reads Spotify's current volume before applying a bounded change.
Gestures are heuristic and may need tuning for your hand and lighting. Volume control
depends on support from the active Spotify device; the app reports unsupported devices.

Clickable buttons also work without gestures. **G** enables/disables gestures,
**C** connects, **Space** plays/pauses, **N/P** skips next/previous, **Q/Escape** exits.

## Try without Spotify

```powershell
.\.venv\Scripts\python.exe air_music.py --demo
```

Demo mode uses the real webcam and gestures with a simulated player. It sends no
Spotify requests and plays no audio. The normal app processes camera frames locally
and sends only playback commands to Spotify; no camera images are saved or uploaded.

## Checks and troubleshooting

```powershell
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe air_music.py --preview music-preview.png
```

- Invalid redirect: compare the dashboard URI exactly, including `/callback`.
- No active device: open Spotify and play a song there, then retry.
- Access denied: verify Premium, developer-app user access, and device restrictions.
- Port busy: close another Air Music instance before connecting.
- Camera trouble: use `--camera 0 --backend dshow`; close other camera apps.
- Rate limits: the worker observes Spotify's Retry-After. Gesture commands expire
  after two seconds; button commands wait up to 30 seconds. Expiry is reported.

Fresh installation requires Python 3.11: create `.venv`, then install `requirements.txt`.
The hand model downloads from Google on first run if it isn't already in `models/`.

References: [PKCE login](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow),
[redirect URIs](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri),
[playback API](https://developer.spotify.com/documentation/web-api/reference/get-information-about-the-users-current-playback).
