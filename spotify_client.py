"""Spotify PKCE sign-in and a nonblocking, rate-limited playback worker."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import queue
import secrets
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, urlopen
import webbrowser

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
REDIRECT_URI = 'http://127.0.0.1:8888/callback'
SCOPES = ('user-read-playback-state user-modify-playback-state '
          'playlist-read-private playlist-read-collaborative')


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


class SpotifyError(Exception):
    pass


def describe_error(error):
    """Useful diagnostics without exposing URLs, OAuth codes, or tokens."""
    if isinstance(error, SpotifyError):
        return str(error)
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'Spotify TLS certificate check failed. Check system date and HTTPS inspection settings.'
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'Spotify request timed out. Check your internet connection.'
    if isinstance(reason, socket.gaierror):
        return 'Cannot resolve Spotify server address (DNS). Check DNS or VPN settings.'
    code = getattr(reason, 'winerror', None) or getattr(reason, 'errno', None)
    if code in (10048, 98, 48):
        return 'Login port 8888 is busy. Close other Air Music instances, then reconnect.'
    if code in (10013, 13):
        return 'Connection permission denied. Check firewall or security software access for Python.'
    if isinstance(reason, ConnectionRefusedError):
        return 'Connection to Spotify was refused. Check proxy or firewall settings.'
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError)):
        return 'Spotify connection was interrupted. Retrying shortly.'
    if isinstance(error, (ValueError, KeyError, TypeError)):
        return 'Spotify returned an unexpected response. Reconnect; this is not necessarily an internet issue.'
    return f'Spotify connection failed ({type(reason).__name__}' + (f', code {code}' if code else '') + '). Try reconnecting.'


class SpotifyClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.access_token = self.refresh_token = None
        self.expires = self.retry_at = 0
        config_path = ROOT / 'spotify_config.json'
        token_path = ROOT / '.spotify_token.json'
        if token_path.exists() and config_path.exists():
            try:
                cfg = json.loads(config_path.read_text())
                if cfg.get('client_id') == client_id:
                    saved = json.loads(token_path.read_text())
                    self.refresh_token = saved.get('refresh_token')
            except Exception:
                pass

    def token(self, fields):
        fields['client_id'] = self.client_id
        request = Request('https://accounts.spotify.com/api/token',
                          data=urlencode(fields).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with urlopen(request, timeout=10) as response:
                data = json.load(response)
        except HTTPError as error:
            raise SpotifyError(f'Login failed ({error.code}). Check Client ID and app settings.') from None
        self.access_token = data['access_token']
        self.refresh_token = data.get('refresh_token', self.refresh_token)
        self.expires = time.monotonic() + data['expires_in'] - 60
        if self.refresh_token:
            try:
                (ROOT / '.spotify_token.json').write_text(json.dumps({'refresh_token': self.refresh_token}))
            except Exception:
                pass

    def login(self, stop):
        if not self.client_id:
            raise SpotifyError('Set SPOTIFY_CLIENT_ID first; see README.md.')
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(24)
        result = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log authorization codes.

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                valid = parsed.path == '/callback' and secrets.compare_digest(query.get('state', [''])[0], state)
                self.send_response(200 if valid else 400)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                if not valid:
                    self.wfile.write(b'Invalid callback. Return to Air Music and reconnect.')
                    return
                result.update(code=query.get('code', [None])[0], error=query.get('error', [None])[0])
                self.wfile.write(b'You can return to Air Music. It will finish connecting shortly.')

        with HTTPServer(('127.0.0.1', 8888), Callback) as server:
            server.timeout = 0.5
            params = dict(client_id=self.client_id, response_type='code', redirect_uri=REDIRECT_URI,
                          scope=SCOPES, state=state, code_challenge_method='S256',
                          code_challenge=pkce_challenge(verifier))
            if not webbrowser.open('https://accounts.spotify.com/authorize?' + urlencode(params)):
                raise SpotifyError('Could not open your browser. Check the default browser and reconnect.')
            deadline = time.monotonic() + 180
            while not result and not stop.is_set() and time.monotonic() < deadline:
                server.handle_request()
        if stop.is_set():
            return
        if not result.get('code'):
            raise SpotifyError('Login cancelled or timed out. Click Connect to retry.')
        self.token(dict(grant_type='authorization_code', code=result['code'],
                        redirect_uri=REDIRECT_URI, code_verifier=verifier))

    def api(self, method, path, retry=True, body=None):
        if time.monotonic() < self.retry_at:
            raise SpotifyError('Spotify rate limit: waiting before more requests.')
        if not self.access_token:
            raise SpotifyError('Connect Spotify first.')
        if time.monotonic() >= self.expires:
            self.token(dict(grant_type='refresh_token', refresh_token=self.refresh_token))
        resource = path if path.startswith(('/me/', '/playlists/')) else '/me/player' + path
        request = Request('https://api.spotify.com/v1' + resource, method=method,
                          headers={'Authorization': 'Bearer ' + self.access_token,
                                   'Content-Type': 'application/json'},
                          data=json.dumps(body).encode() if body is not None else
                          (b'' if method in ('PUT', 'POST') else None))
        try:
            with urlopen(request, timeout=8) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            if error.code == 401 and retry:
                self.expires = 0
                return self.api(method, path, retry=False, body=body)
            if error.code == 429:
                try:
                    delay = max(1, float(error.headers.get('Retry-After', '5')))
                except ValueError:
                    delay = 5
                self.retry_at = time.monotonic() + delay
                raise SpotifyError(f'Spotify rate limit: retrying after {delay:g}s.') from None
            messages = {403: 'Spotify denied this action. Check Premium, app access, and device restrictions.',
                        404: 'Open Spotify and start a song on your desired device first.',
                        401: 'Spotify session expired. Click Connect again.'}
            raise SpotifyError(messages.get(error.code, f'Spotify request failed ({error.code}).')) from None


class PlaybackWorker:
    def __init__(self, client_id):
        self.client = SpotifyClient(client_id)
        self.stop = threading.Event()
        self.commands = queue.Queue(maxsize=4)
        self.lock = threading.Lock()
        self.state = {'message': 'Connect Spotify to get started', 'connected': False,
                      'playback': {}, 'art': None, 'busy': False,
                      'playlists': [], 'library_offset': 0, 'library_total': 0,
                      'selected_playlist': None, 'tracks': [], 'tracks_offset': 0,
                      'tracks_total': 0, 'library_loading': False, 'tracks_loading': False,
                      'library_message': 'Connect Spotify to load your library.'}
        self.pending_volume = None
        self.art_url = None
        self.recovering = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return self.state.copy()

    def set(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)

    def submit(self, action, value=None, manual=False):
        if self.snapshot()['busy']:
            self.set(message='Finish Spotify sign-in before using playback controls.')
            return
        if action != 'connect' and not self.client.access_token:
            self.set(message='Connect Spotify first, then start a song in Spotify.')
            return
        if action == 'volume':
            with self.lock:
                self.pending_volume = max(0, min(100, int(value)))
            return
        try:
            self.commands.put_nowait((action, value, time.monotonic(), 30 if manual or action == 'connect' else 2))
            self.set(message=f'{action.capitalize()} queued for Spotify...')
        except queue.Full:
            self.set(message='Spotify is still processing controls. Wait, then try again.')

    def poll(self):
        playback = self.client.api('GET', '') or {}
        self.set(playback=playback, connected=True)
        if self.recovering:
            self.set(message='Connection restored.' if playback else 'Connected. Open Spotify and start a song.')
            self.recovering = False
        item = playback.get('item') or {}
        images = (item.get('album') or item).get('images') or []
        url = images[0]['url'] if images else None
        if url != self.art_url:
            self.art_url = url
            self.set(art=None)
            if url and urlsplit(url).scheme == 'https':
                try:
                    with urlopen(url, timeout=5) as response:
                        art = Image.open(io.BytesIO(response.read(5_000_000))).convert('RGB')
                    self.set(art=art)
                except (OSError, ValueError):
                    pass

    def load_library(self, offset=0):
        self.set(library_loading=True, library_message='Loading your playlists...')
        try:
            page = self.client.api('GET', f'/me/playlists?limit=50&offset={max(0, int(offset))}') or {}
            self.set(playlists=[p for p in page.get('items', []) if p],
                     library_offset=page.get('offset', offset), library_total=page.get('total', 0),
                     library_message='Select a playlist to browse its songs.' if page.get('items') else 'No playlists found in your library.')
        except (SpotifyError, OSError, ValueError, KeyError, TypeError) as error:
            self.set(library_message=describe_error(error))
        finally:
            self.set(library_loading=False)

    def load_tracks(self, selection):
        playlist, offset = selection['playlist'], max(0, int(selection.get('offset', 0)))
        playlist_id = playlist['id']
        if not playlist_id.isalnum():
            raise SpotifyError('Invalid playlist ID.')
        self.set(selected_playlist=playlist, playlist_art=None, tracks=[], tracks_loading=True,
                 tracks_offset=offset, tracks_total=0, library_message='Loading songs...')
        try:
            page = self.client.api('GET', f'/playlists/{playlist_id}/items?limit=50&offset={offset}') or {}
            rows = []
            for index, entry in enumerate(page.get('items') or []):
                entry = entry or {}
                track = entry.get('item') or entry.get('track') or {}
                rows.append({'track': track, 'position': offset+index,
                             'playable': bool(track.get('uri')) and not entry.get('is_local')
                             and not track.get('is_local') and track.get('is_playable') is not False})
            self.set(tracks=rows, tracks_total=page.get('total', len(rows)),
                     library_message='Click a song to play it on your active Spotify device.' if rows else 'This playlist has no available songs.')
            images = playlist.get('images') or []
            if images and urlsplit(images[0]['url']).scheme == 'https':
                try:
                    with urlopen(images[0]['url'], timeout=4) as response:
                        art = Image.open(io.BytesIO(response.read(5_000_000))).convert('RGB')
                    self.set(playlist_art=art)
                except (OSError, ValueError):
                    pass
        except (SpotifyError, OSError, ValueError, KeyError, TypeError) as error:
            self.set(library_message='Cannot load songs. Reconnect for playlist access; Spotify may restrict this playlist.'
                     if isinstance(error, SpotifyError) else describe_error(error))
        finally:
            self.set(tracks_loading=False)

    def run(self):
        poll_at, volume_at = 0, 0
        while not self.stop.wait(0.05):
            now = time.monotonic()
            if now < self.client.retry_at:
                continue
            try:
                try:
                    action, value, created, ttl = self.commands.get_nowait()
                    if now - created > ttl:
                        self.set(message='Control expired while Spotify was busy. Please try again.')
                        continue
                except queue.Empty:
                    action = None
                if action == 'connect':
                    self.set(busy=True, message='Connecting to Spotify...')
                    try:
                        if self.client.refresh_token and not self.client.access_token:
                            try:
                                self.client.token(dict(grant_type='refresh_token', refresh_token=self.client.refresh_token))
                            except Exception:
                                self.client.login(self.stop)
                        else:
                            self.client.login(self.stop)
                    finally:
                        self.set(busy=False)
                    if self.stop.is_set():
                        break
                    self.set(connected=True, message='Connected. Open Spotify and start a song.')
                    self.load_library()
                    poll_at = 0
                elif action:
                    if action == 'library':
                        self.load_library(value or 0)
                    elif action == 'playlist':
                        self.load_tracks(value)
                    elif action == 'play_track':
                        self.client.api('PUT', '/play', body={
                            'context_uri': value['context_uri'],
                            'offset': {'position': int(value['position'])}})
                        self.set(message='Song sent to Spotify')
                        poll_at = now+0.4
                    if action == 'volume_step':
                        # Base each step on Spotify's current level, not a delayed UI value.
                        playback = self.client.api('GET', '') or {}
                        device = playback.get('device') or {}
                        current = device.get('volume_percent')
                        if current is None or device.get('supports_volume') is False:
                            raise SpotifyError('Volume unavailable on this Spotify device.')
                        self.set(playback=playback)
                        with self.lock:
                            self.pending_volume = max(0, min(100, current + value))
                    methods = {'play': ('PUT', '/play'), 'pause': ('PUT', '/pause'),
                               'next': ('POST', '/next'), 'previous': ('POST', '/previous')}
                    if action in methods:
                        self.client.api(*methods[action])
                        self.set(message=action.capitalize() + ' sent to Spotify')
                        poll_at = now + 0.4
                if now >= volume_at:
                    with self.lock:
                        volume, self.pending_volume = self.pending_volume, None
                    if volume is not None:
                        device = self.snapshot()['playback'].get('device') or {}
                        if not device or device.get('supports_volume') is False:
                            raise SpotifyError('This Spotify device does not expose volume control.')
                        self.client.api('PUT', '/volume?' + urlencode({'volume_percent': volume}))
                        playback = self.snapshot()['playback'].copy()
                        playback['device'] = dict(playback.get('device') or {}, volume_percent=volume)
                        self.set(playback=playback)
                        self.set(message=f'Volume set to {volume}%')
                        volume_at = now + 0.65
                if self.client.access_token and now >= poll_at:
                    poll_at = now + 2
                    self.poll()
            except (SpotifyError, URLError, OSError, ValueError, KeyError, TypeError) as error:
                self.recovering = not isinstance(error, SpotifyError)
                self.set(message=describe_error(error))
                poll_at = time.monotonic() + 5

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
