"""Gesture-controlled Spotify remote. Run --demo to try it without sign-in."""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.request
import webbrowser

if os.name == 'nt':
    # Run before window creation so Windows does not bitmap-stretch the UI.
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass

os.environ.setdefault('OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS', '0')
import cv2
import mediapipe as mp
import numpy as np

from gestures import Gestures
from music_ui import MusicUI
from spotify_client import PlaybackWorker

ROOT = Path(__file__).resolve().parent
WINDOW = 'Air Music'


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
                  'owner': {'display_name': 'Air Music demo'}} for i,name in enumerate(
                  ('Late night focus', 'Morning light', 'On repeat', 'Weekend drive', 'Quiet hours'))]
    tracks = [{'track': {'uri': 'spotify:track:demo'+str(i), 'name': name,
                         'artists': [{'name': artist}], 'album': {'name': album}, 'duration_ms': 180000+i*11000},
               'position': i, 'playable': True} for i,(name,artist,album) in enumerate([
                  ('After the rain', 'Paper Satellites', 'Night windows'),
                  ('Soft signals', 'North Avenue', 'Small hours'),
                  ('Coastline', 'The Slow Current', 'Open water'),
                  ('Another sky', 'Luna Park', 'Blue room'),
                  ('Stay a little longer', 'Paper Satellites', 'Night windows'),
                  ('Homeward', 'North Avenue', 'Small hours'),
                  ('Daybreak', 'Luna Park', 'Blue room'),
                  ('Passing lights', 'The Slow Current', 'Open water')])]
    return {'connected': False, 'art': None, 'message': 'Demo only: sample playlists and songs; no Spotify requests.',
            'playlists': playlists, 'selected_playlist': playlists[0], 'tracks': tracks,
            'library_total': len(playlists), 'tracks_total': len(tracks),
            'library_message': 'Click any demo song to preview the player.',
            'playback': {'is_playing': True, 'progress_ms': 65000,
                         'device': {'name': 'Demo player', 'volume_percent': 40},
                         'item': tracks[0]['track']}}




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--backend', choices=('dshow', 'msmf', 'auto'), default='dshow' if os.name == 'nt' else 'auto')
    parser.add_argument('--client-id', default=os.environ.get('SPOTIFY_CLIENT_ID', ''))
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--preview', type=Path, help='Save a sample UI image without opening a camera')
    args = parser.parse_args()
    ui = MusicUI()
    if args.preview:
        image = ui.render(np.full((480, 640, 3), 28, np.uint8), demo_state(), 'Ready for a gesture', 0, True, True)
        if not cv2.imwrite(str(args.preview), image):
            raise OSError('Could not save preview')
        return
    config = ROOT / 'spotify_config.json'
    if not args.client_id and config.exists():
        args.client_id = json.loads(config.read_text()).get('client_id', '')
    model = ensure_model()
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.65, min_hand_presence_confidence=0.65)
    camera = cv2.VideoCapture(args.camera, {'dshow': cv2.CAP_DSHOW, 'msmf': cv2.CAP_MSMF, 'auto': cv2.CAP_ANY}[args.backend])
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    worker = None
    TARGET_FRAME_TIME = 1.0 / 30.0
    try:
        if not camera.isOpened():
            raise RuntimeError('Cannot open camera. Close Windows Camera and try --camera 0 --backend dshow.')
        worker = None if args.demo else PlaybackWorker(args.client_id)
        demo = demo_state()
        gestures, enabled, timestamp = Gestures(), False, -1
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW, 1200, 800)
        cv2.setMouseCallback(WINDOW, ui.mouse)
        with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
            while True:
                frame_start = time.monotonic()
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise RuntimeError('Camera stopped delivering frames.')
                frame = cv2.flip(frame, 1)
                hand = None
                if enabled:
                    # Fast MediaPipe inference on 320px downscaled frame
                    h, w = frame.shape[:2]
                    det_w = 320
                    det_h = max(1, int(h * (det_w / max(1, w))))
                    det_frame = cv2.resize(frame, (det_w, det_h), interpolation=cv2.INTER_LINEAR)
                    timestamp = max(timestamp + 1, time.monotonic_ns() // 1_000_000)
                    result = detector.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=cv2.cvtColor(det_frame, cv2.COLOR_BGR2RGB)), timestamp)
                    hand = result.hand_landmarks[0] if result.hand_landmarks else None
                state = demo if args.demo else worker.snapshot()
                device = (state.get('playback') or {}).get('device') or {}
                current_volume = device.get('volume_percent') if device.get('supports_volume') is not False else None
                command = gestures.update(hand if enabled else None, time.monotonic(), current_volume,
                                          frame.shape[1] / frame.shape[0])
                if hand:
                    for point in hand:
                        cv2.circle(frame, (int(point.x*frame.shape[1]), int(point.y*frame.shape[0])), 3, (126, 244, 185), -1, cv2.LINE_AA)
                try:
                    _, _, view_width, view_height = cv2.getWindowImageRect(WINDOW)
                    if view_width > 0 and view_height > 0:
                        ui.set_viewport(view_width, view_height)
                except cv2.error:
                    pass
                display = ui.render(frame, state, gestures.label, gestures.progress, enabled, args.demo)
                cv2.imshow(WINDOW, display)
                elapsed = time.monotonic() - frame_start
                wait_ms = max(1, int((TARGET_FRAME_TIME - elapsed) * 1000))
                key = cv2.waitKey(wait_ms) & 0xFF
                if key in (27, ord('q')) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) == 0:
                    break
                action = ui.actions.pop(0) if ui.actions else {ord('c'): 'connect', ord('g'): 'gestures',
                           ord(' '): 'toggle', ord('n'): 'next', ord('p'): 'previous'}.get(key)
                if isinstance(action, tuple):
                    if action[0] == 'open_url':
                        if action[1].startswith('https://open.spotify.com/'):
                            webbrowser.open(action[1])
                        command = None
                    else:
                        command = action
                elif action == 'gestures':
                    enabled = not enabled
                    gestures = Gestures()
                    command = None
                elif action == 'open_track':
                    url = ((state.get('playback') or {}).get('item') or {}).get('external_urls', {}).get('spotify', '')
                    if url.startswith('https://open.spotify.com/'):
                        webbrowser.open(url)
                elif action:
                    playback = state.get('playback') or {}
                    if action == 'toggle':
                        action = 'pause' if playback.get('is_playing') else 'play'
                    if action in ('louder', 'quieter'):
                        volume = (playback.get('device') or {}).get('volume_percent')
                        command = ('volume', max(0, min(100, volume+(5 if action == 'louder' else -5)))) if volume is not None else None
                    else:
                        command = (action, None)
                if command:
                    if args.demo:
                        name, value = command
                        demo['message'] = f'Demo gesture: {name}' + (f' {value}%' if value is not None else '')
                        if name == 'playlist':
                            demo['selected_playlist'] = value['playlist']
                        elif name == 'play_track':
                            demo['playback']['item'] = demo['tracks'][value['position']]['track']
                            demo['playback']['progress_ms'] = 0
                            demo['playback']['is_playing'] = True
                        elif name in ('next', 'previous'):
                            uri = demo['playback']['item']['uri']
                            index = next((i for i,r in enumerate(demo['tracks']) if r['track']['uri'] == uri),0)
                            index = (index+(1 if name == 'next' else -1)) % len(demo['tracks'])
                            demo['playback']['item'] = demo['tracks'][index]['track']
                            demo['playback']['progress_ms'] = 0
                        elif name in ('play', 'pause'):
                            demo['playback']['is_playing'] = name == 'play'
                        elif name == 'volume_step':
                            device = demo['playback']['device']
                            device['volume_percent'] = max(0, min(100, device['volume_percent'] + value))
                        elif name == 'volume':
                            demo['playback']['device']['volume_percent'] = value
                    else:
                        worker.submit(*command, manual=action is not None)
    finally:
        if worker:
            worker.close()
        camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        raise SystemExit(f'Air Music: {error}')
