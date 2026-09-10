"""Spotify PKCE sign-in and a nonblocking, rate-limited playback worker."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import queue
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, urlopen
import webbrowser

from PIL import Image

REDIRECT_URI = 'http://127.0.0.1:8888/callback'
SCOPES = 'user-read-playback-state user-modify-playback-state'


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


class SpotifyError(Exception):
    pass


class SpotifyClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.access_token = self.refresh_token = None
        self.expires = self.retry_at = 0

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

    def api(self, method, path, retry=True):
        if time.monotonic() < self.retry_at:
            raise SpotifyError('Spotify rate limit: waiting before more requests.')
        if not self.access_token:
            raise SpotifyError('Connect Spotify first.')
        if time.monotonic() >= self.expires:
            self.token(dict(grant_type='refresh_token', refresh_token=self.refresh_token))
        request = Request('https://api.spotify.com/v1/me/player' + path, method=method,
                          headers={'Authorization': 'Bearer ' + self.access_token},
                          data=b'' if method in ('PUT', 'POST') else None)
        try:
            with urlopen(request, timeout=8) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            if error.code == 401 and retry:
                self.expires = 0
                return self.api(method, path, retry=False)
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
                      'playback': {}, 'art': None, 'busy': False}
        self.pending_volume = None
        self.art_url = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return self.state.copy()

    def set(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)

    def submit(self, action, value=None):
        if self.snapshot()['busy']:
            return
        if action == 'volume':
            with self.lock:
                self.pending_volume = max(0, min(100, int(value)))
            return
        try:
            self.commands.put_nowait((action, value, time.monotonic()))
        except queue.Full:
            pass

    def poll(self):
        playback = self.client.api('GET', '') or {}
        self.set(playback=playback, connected=True)
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

    def run(self):
        poll_at, volume_at = 0, 0
        while not self.stop.wait(0.05):
            now = time.monotonic()
            if now < self.client.retry_at:
                continue
            try:
                try:
                    action, value, created = self.commands.get_nowait()
                    if now - created > 2:
                        continue
                except queue.Empty:
                    action = None
                if action == 'connect':
                    self.set(busy=True, message='Finish signing in in your browser')
                    try:
                        self.client.login(self.stop)
                    finally:
                        self.set(busy=False)
                    if self.stop.is_set():
                        break
                    self.set(connected=True, message='Connected. Open Spotify and start a song.')
                    poll_at = 0
                elif action:
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
                        self.set(message=f'Volume set to {volume}%')
                        volume_at = now + 0.65
                if self.client.access_token and now >= poll_at:
                    poll_at = now + 2
                    self.poll()
            except (SpotifyError, URLError, OSError, ValueError, KeyError) as error:
                self.set(message=str(error) if isinstance(error, SpotifyError) else 'Connection problem. Check internet and app settings.')
                poll_at = time.monotonic() + 5

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
