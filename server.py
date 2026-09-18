"""Handsfree Web Server. Bridges OpenCV camera and MediaPipe gestures to React frontend."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import io
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import webbrowser

import cv2
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from gestures import Gestures
from spotify_client import PlaybackWorker

ROOT = Path(__file__).resolve().parent

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]


class ThreadedCamera:
    """Read camera frames on a background thread to decouple USB latency."""

    def __init__(self, index, backend):
        self.cap = cv2.VideoCapture(index, backend)
        self._frame = None
        self._ok = False
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            with self._lock:
                self._ok, self._frame = ok, frame

    def isOpened(self):
        return self.cap.isOpened()

    def read(self):
        with self._lock:
            if self._frame is None:
                return False, None
            return self._ok, self._frame.copy()

    def release(self):
        self._running = False
        self._thread.join(timeout=1.0)
        self.cap.release()


class HandSmoother:
    """Exponential Moving Average filter for hand landmarks."""

    def __init__(self, alpha=0.45):
        self.alpha = alpha
        self.prev = None

    def smooth(self, hand):
        if hand is None:
            self.prev = None
            return None
        if self.prev is None or len(self.prev) != len(hand):
            self.prev = [(p.x, p.y, p.z) for p in hand]
            return hand
        smoothed = []
        new_prev = []
        for i, point in enumerate(hand):
            sx = self.prev[i][0] + self.alpha * (point.x - self.prev[i][0])
            sy = self.prev[i][1] + self.alpha * (point.y - self.prev[i][1])
            sz = self.prev[i][2] + self.alpha * (point.z - self.prev[i][2])
            new_prev.append((sx, sy, sz))
            from types import SimpleNamespace
            smoothed.append(SimpleNamespace(x=sx, y=sy, z=sz))
        self.prev = new_prev
        return smoothed


def draw_hand_skeleton(frame, hand):
    """Draw glowing neon skeleton lines and landmark dots on the camera frame."""
    h, w = frame.shape[:2]

    def pt(idx):
        return (int(hand[idx].x * w), int(hand[idx].y * h))

    for a, b in HAND_CONNECTIONS:
        p1, p2 = pt(a), pt(b)
        cv2.line(frame, p1, p2, (20, 100, 60), 5, cv2.LINE_AA)
        cv2.line(frame, p1, p2, (80, 220, 140), 2, cv2.LINE_AA)

    tips = {4, 8, 12, 16, 20}
    for i, point in enumerate(hand):
        center = pt(i)
        if i in tips:
            cv2.circle(frame, center, 6, (20, 120, 70), -1, cv2.LINE_AA)
            cv2.circle(frame, center, 4, (126, 255, 185), -1, cv2.LINE_AA)
        else:
            cv2.circle(frame, center, 4, (20, 100, 60), -1, cv2.LINE_AA)
            cv2.circle(frame, center, 2, (100, 230, 160), -1, cv2.LINE_AA)


def ensure_model():
    model = ROOT / 'models' / 'hand_landmarker.task'
    if not model.exists():
        model.parent.mkdir(exist_ok=True)
        temporary = model.with_suffix('.tmp')
        print('Downloading hand model...')
        try:
            url = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'
            with urllib.request.urlopen(url, timeout=60) as response:
                temporary.write_bytes(response.read())
            temporary.replace(model)
        finally:
            temporary.unlink(missing_ok=True)
    return model


def demo_state():
    playlists = [{'id': 'demo'+str(i), 'uri': 'spotify:playlist:demo'+str(i), 'name': name,
                  'owner': {'display_name': 'Handsfree demo'}} for i, name in enumerate(
                  ('Late night focus', 'Morning light', 'On repeat', 'Weekend drive', 'Quiet hours'))]
    tracks = [{'track': {'uri': 'spotify:track:demo'+str(i), 'name': name,
                         'artists': [{'name': artist}], 'album': {'name': album}, 'duration_ms': 180000+i*11000},
               'position': i, 'playable': True} for i, (name, artist, album) in enumerate([
                  ('After the rain', 'Paper Satellites', 'Night windows'),
                  ('Soft signals', 'North Avenue', 'Small hours'),
                  ('Coastline', 'The Slow Current', 'Open water'),
                  ('Another sky', 'Luna Park', 'Blue room'),
                  ('Stay a little longer', 'Paper Satellites', 'Night windows'),
                  ('Homeward', 'North Avenue', 'Small hours'),
                  ('Daybreak', 'Luna Park', 'Blue room'),
                  ('Passing lights', 'The Slow Current', 'Open water')])]
    return {'connected': False, 'art': None, 'message': 'Demo mode: sample playlists and songs.',
            'playlists': playlists, 'selected_playlist': playlists[0], 'tracks': tracks,
            'library_total': len(playlists), 'tracks_total': len(tracks),
            'library_message': 'Click any song or swipe with your hand to control playback.',
            'playback': {'is_playing': True, 'progress_ms': 65000,
                         'device': {'name': 'Demo player', 'volume_percent': 40, 'supports_volume': True},
                         'item': tracks[0]['track']}}


class AppState:
    def __init__(self, demo=False, client_id=''):
        self.demo = demo
        self.client_id = client_id
        self.worker = None if demo else PlaybackWorker(client_id)
        self.demo_data = demo_state()
        self.gestures = Gestures()
        self.gestures_enabled = True
        self.latest_jpeg = b''
        self.lock = threading.Lock()
        self.connections = set()
        self.last_gesture_time = 0.0
        self.demo_progress_base = time.monotonic()
        self.latest_command = None

    def execute_action(self, action, value=None):
        with self.lock:
            if action == 'toggle_gestures':
                self.gestures_enabled = not self.gestures_enabled
                self.gestures = Gestures()
                return

            if action == 'connect':
                print('[Handsfree] Connect requested! Initiating Spotify sign-in flow...')
                self.demo = False
                if not self.worker:
                    self.worker = PlaybackWorker(self.client_id)
                self.worker.submit('connect', None, manual=True)
                return

            if action == 'demo':
                self.demo = True
                return

            if self.demo:
                data = self.demo_data
                if action == 'toggle':
                    data['playback']['is_playing'] = not data['playback'].get('is_playing', False)
                    self.demo_progress_base = time.monotonic()
                elif action == 'play':
                    data['playback']['is_playing'] = True
                    self.demo_progress_base = time.monotonic()
                elif action == 'pause':
                    data['playback']['is_playing'] = False
                    self.demo_progress_base = time.monotonic()
                elif action == 'next' or action == 'previous':
                    tracks = data['tracks']
                    curr_uri = data['playback']['item']['uri']
                    idx = next((i for i, r in enumerate(tracks) if r['track']['uri'] == curr_uri), 0)
                    new_idx = (idx + (1 if action == 'next' else -1)) % len(tracks)
                    data['playback']['item'] = tracks[new_idx]['track']
                    data['playback']['progress_ms'] = 0
                    self.demo_progress_base = time.monotonic()
                elif action == 'volume':
                    device = data['playback']['device']
                    device['volume_percent'] = max(0, min(100, int(value)))
                elif action == 'playlist':
                    target_id = value.get('id') if isinstance(value, dict) else value
                    for p in data['playlists']:
                        if p['id'] == target_id:
                            data['selected_playlist'] = p
                            break
                elif action == 'play_track':
                    pos = int(value.get('position', 0)) if isinstance(value, dict) else int(value)
                    if 0 <= pos < len(data['tracks']):
                        data['playback']['item'] = data['tracks'][pos]['track']
                        data['playback']['progress_ms'] = 0
                        data['playback']['is_playing'] = True
                        self.demo_progress_base = time.monotonic()
            else:
                if self.worker:
                    snap = self.worker.snapshot()
                    if action == 'toggle':
                        is_playing = bool((snap.get('playback') or {}).get('is_playing'))
                        cmd = 'pause' if is_playing else 'play'
                        self.worker.submit(cmd, None, manual=True)
                    elif action == 'play_track':
                        if isinstance(value, dict) and 'context_uri' in value:
                            track_val = value
                        else:
                            pos = int(value.get('position', 0)) if isinstance(value, dict) else int(value)
                            curr_playlist = snap.get('selected_playlist') or {}
                            track_val = {'context_uri': curr_playlist.get('uri'), 'position': pos}
                        self.worker.submit('play_track', track_val, manual=True)
                    elif action == 'volume':
                        vol = max(0, min(100, int(value)))
                        self.worker.submit('volume', vol, manual=True)
                    elif action == 'playlist':
                        p_val = {'playlist': value, 'offset': 0} if isinstance(value, dict) and 'id' in value else value
                        self.worker.submit('playlist', p_val, manual=True)
                    else:
                        self.worker.submit(action, value, manual=True)

    def get_snapshot(self):
        with self.lock:
            if self.demo:
                data = self.demo_data
                if data['playback']['is_playing']:
                    now = time.monotonic()
                    elapsed = now - self.demo_progress_base
                    dur = (data['playback']['item'] or {}).get('duration_ms', 999999)
                    data['playback']['progress_ms'] = min(
                        data['playback']['progress_ms'] + int(elapsed * 1000), dur)
                    self.demo_progress_base = now
                else:
                    self.demo_progress_base = time.monotonic()
                snap = dict(data)
            else:
                snap = self.worker.snapshot() if self.worker else {}

            # Serialize state for JSON
            cleaned_snap = {
                'connected': bool(snap.get('connected', False)),
                'message': snap.get('message', ''),
                'library_message': snap.get('library_message', ''),
                'playlists': snap.get('playlists', []),
                'selected_playlist': snap.get('selected_playlist'),
                'tracks': snap.get('tracks', []),
                'tracks_loading': snap.get('tracks_loading', False),
                'playback': snap.get('playback', {}),
                'gestures_enabled': self.gestures_enabled,
                'gesture_label': self.gestures.label,
                'gesture_progress': self.gestures.progress,
                'demo': self.demo,
            }
            return cleaned_snap


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(broadcast_loop())
    yield
    task.cancel()


app = FastAPI(title='Handsfree Backend', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

state_manager: AppState = None


@app.get('/api/state')
def api_state():
    if not state_manager:
        return JSONResponse({'error': 'Server not ready'}, status_code=503)
    return JSONResponse(state_manager.get_snapshot())


@app.post('/api/action')
async def api_action(body: dict):
    if not state_manager:
        return JSONResponse({'error': 'Server not ready'}, status_code=503)
    action = body.get('action')
    value = body.get('value')
    state_manager.execute_action(action, value)
    return JSONResponse({'status': 'ok'})


@app.get('/api/connect')
def api_connect():
    if not state_manager:
        return JSONResponse({'error': 'Server not ready'}, status_code=503)
    state_manager.execute_action('connect')
    return JSONResponse({'status': 'connecting'})


@app.get('/api/video_feed')
async def video_feed():
    async def frame_generator():
        try:
            while True:
                jpeg = state_manager.latest_jpeg if state_manager else b''
                if jpeg:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
                await asyncio.sleep(0.033)
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        frame_generator(),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )


@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if state_manager:
        state_manager.connections.add(websocket)
    try:
        # Loop receiving actions from frontend
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            action = msg.get('action')
            value = msg.get('value')
            if action:
                state_manager.execute_action(action, value)
    except WebSocketDisconnect:
        if state_manager and websocket in state_manager.connections:
            state_manager.connections.remove(websocket)
    except Exception:
        if state_manager and websocket in state_manager.connections:
            state_manager.connections.remove(websocket)


async def broadcast_loop():
    while True:
        if state_manager and state_manager.connections:
            snapshot = state_manager.get_snapshot()
            data_str = json.dumps({'type': 'state', 'data': snapshot})
            dead_sockets = set()
            for ws in list(state_manager.connections):
                try:
                    await ws.send_text(data_str)
                except Exception:
                    dead_sockets.add(ws)
            state_manager.connections -= dead_sockets
        await asyncio.sleep(0.04)  # ~25 updates per second for ultra-responsive UI


def vision_loop(camera, options, state_mgr):
    smoother = HandSmoother(alpha=0.45)
    timestamp = -1

    with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue

            frame = cv2.flip(frame, 1)
            raw_hand = None

            if state_mgr.gestures_enabled:
                h, w = frame.shape[:2]
                det_w = 320
                det_h = max(1, int(h * (det_w / max(1, w))))
                det_frame = cv2.resize(frame, (det_w, det_h), interpolation=cv2.INTER_LINEAR)
                timestamp = max(timestamp + 1, time.monotonic_ns() // 1_000_000)
                result = detector.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(det_frame, cv2.COLOR_BGR2RGB)), timestamp)
                raw_hand = result.hand_landmarks[0] if result.hand_landmarks else None

            hand = smoother.smooth(raw_hand if state_mgr.gestures_enabled else None)

            snap = state_mgr.get_snapshot()
            device = (snap.get('playback') or {}).get('device') or {}
            curr_vol = device.get('volume_percent')

            command = state_mgr.gestures.update(
                hand if state_mgr.gestures_enabled else None,
                time.monotonic(),
                curr_vol,
                frame.shape[1] / frame.shape[0]
            )

            if hand:
                draw_hand_skeleton(frame, hand)

            if command:
                name, val = command
                state_mgr.execute_action(name, val)

            # Compress video frame to JPEG for HTTP stream
            preview_frame = cv2.resize(frame, (480, 360), interpolation=cv2.INTER_LINEAR)
            ret, buf = cv2.imencode('.jpg', preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ret:
                state_mgr.latest_jpeg = buf.tobytes()

            time.sleep(0.015)


FRONTEND_DIST = ROOT / 'frontend' / 'dist'
if FRONTEND_DIST.exists():
    app.mount('/assets', StaticFiles(directory=str(FRONTEND_DIST / 'assets')), name='assets')

    @app.get('/')
    def serve_frontend_index():
        return FileResponse(str(FRONTEND_DIST / 'index.html'))


def find_available_port(target_port=8000, max_attempts=10):
    import socket
    for p in range(target_port, target_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', p))
                return p
            except OSError:
                continue
    return target_port


def run_server():
    global state_manager
    parser = argparse.ArgumentParser(description='Handsfree Web Backend')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--backend', choices=('dshow', 'msmf', 'auto'), default='dshow' if os.name == 'nt' else 'auto')
    parser.add_argument('--client-id', default=os.environ.get('SPOTIFY_CLIENT_ID', ''))
    parser.add_argument('--demo', action='store_true', default=False, help='Run in offline demo mode')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    config = ROOT / 'spotify_config.json'
    if not args.client_id and config.exists():
        args.client_id = json.loads(config.read_text()).get('client_id', '')

    backend_map = {'dshow': cv2.CAP_DSHOW, 'msmf': cv2.CAP_MSMF, 'auto': cv2.CAP_ANY}
    camera = ThreadedCamera(args.camera, backend_map[args.backend])

    for _ in range(50):
        if not camera.isOpened():
            break
        ok, frame = camera.read()
        if ok and frame is not None:
            break
        time.sleep(0.02)

    model = ensure_model()
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.65, min_hand_presence_confidence=0.65)

    state_manager = AppState(demo=args.demo, client_id=args.client_id)

    # Start vision worker thread
    v_thread = threading.Thread(target=vision_loop, args=(camera, options, state_manager), daemon=True)
    v_thread.start()

    if not args.demo and state_manager.worker:
        state_manager.worker.submit('connect', None, manual=True)

    port = find_available_port(args.port)

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f'http://localhost:{port}')).start()

    import uvicorn
    print(f'Starting Handsfree Web Server on http://localhost:{port}...')
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    run_server()
