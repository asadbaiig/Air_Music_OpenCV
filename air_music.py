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
    return {'connected': False, 'art': None, 'message': 'Demo only: no Spotify requests are sent.',
            'playback': {'is_playing': True, 'progress_ms': 65000,
                         'device': {'name': 'Demo player', 'volume_percent': 40},
                         'item': {'name': 'Your next favorite song', 'artists': [{'name': 'Air Music demo'}], 'duration_ms': 240000}}}


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
    worker = None
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
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise RuntimeError('Camera stopped delivering frames.')
                frame = cv2.flip(frame, 1)
                timestamp = max(timestamp+1, time.monotonic_ns()//1_000_000)
                result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                                             data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), timestamp)
                hand = result.hand_landmarks[0] if result.hand_landmarks else None
                command = gestures.update(hand if enabled else None, time.monotonic())
                if hand:
                    for point in hand:
                        cv2.circle(frame, (int(point.x*frame.shape[1]), int(point.y*frame.shape[0])), 3, (126, 244, 185), -1, cv2.LINE_AA)
                    a, b = hand[4], hand[8]
                    cv2.line(frame, (int(a.x*frame.shape[1]), int(a.y*frame.shape[0])),
                             (int(b.x*frame.shape[1]), int(b.y*frame.shape[0])), (126, 244, 185), 2, cv2.LINE_AA)
                state = demo if args.demo else worker.snapshot()
                try:
                    _, _, view_width, view_height = cv2.getWindowImageRect(WINDOW)
                    if view_width > 0 and view_height > 0:
                        ui.set_viewport(view_width, view_height)
                except cv2.error:
                    pass
                display = ui.render(frame, state, gestures.label, gestures.progress, enabled, args.demo)
                cv2.imshow(WINDOW, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord('q')) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) == 0:
                    break
                action = ui.actions.pop(0) if ui.actions else {ord('c'): 'connect', ord('g'): 'gestures',
                           ord(' '): 'toggle', ord('n'): 'next', ord('p'): 'previous'}.get(key)
                if action == 'gestures':
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
                        if name in ('play', 'pause'):
                            demo['playback']['is_playing'] = name == 'play'
                        elif name == 'volume':
                            demo['playback']['device']['volume_percent'] = value
                    else:
                        worker.submit(*command)
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
