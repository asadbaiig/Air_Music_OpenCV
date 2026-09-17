import io
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from gestures import Gestures
from spotify_client import SpotifyClient, SpotifyError, PlaybackWorker, pkce_challenge, describe_error
import socket
import threading
import queue
from urllib.error import URLError
from music_ui import MusicUI
import cv2
import numpy as np


def hand(raised=(True, True, True, True), shift=0):
    points = [SimpleNamespace(x=0.5+shift, y=0.8, z=0) for _ in range(21)]
    points[0].y = 0.95
    points[9].y = 0.72
    points[3].x = 0.4+shift
    points[4].x = 0.3+shift
    for tip, up in zip((8, 12, 16, 20), raised):
        points[tip-2].y = 0.65
        points[tip].y = 0.4 if up else 0.85
    return points


class RenderingTests(unittest.TestCase):
    def test_playlist_selection_song_click_and_scrolling(self):
        from air_music import demo_state
        ui = MusicUI()
        state = demo_state()
        frame = np.zeros((480,640,3),dtype=np.uint8)
        ui.render(frame,state,'Ready',0,True,True)
        ui.mouse(cv2.EVENT_LBUTTONDOWN,100,270,0,None)
        self.assertEqual(ui.actions.pop()[0],'playlist')
        ui.mouse(cv2.EVENT_LBUTTONDOWN,400,367,0,None)
        action, payload = ui.actions.pop()
        self.assertEqual(action,'play_track')
        self.assertEqual(payload['position'],0)
        ui.mouse(cv2.EVENT_MOUSEWHEEL,400,500,(-120 & 0xffff)<<16,None)
        ui.render(frame,state,'Ready',0,True,True)
        ui.mouse(cv2.EVENT_LBUTTONDOWN,400,367,0,None)
        self.assertEqual(ui.actions.pop()[1]['position'],2)

    def test_scaled_render_and_click_coordinates(self):
        ui = MusicUI()
        ui.set_viewport(1500, 1000)
        frame = ui.render(np.zeros((240, 320, 3), dtype=np.uint8),
                          {'connected': False}, 'Ready', 0, False)
        self.assertEqual(frame.shape, (1000, 1500, 3))
        ui.mouse(cv2.EVENT_LBUTTONDOWN, round(1050*1.25), round(50*1.25), 0, None)
        self.assertEqual(ui.actions, ['connect'])


class GestureTests(unittest.TestCase):
    def test_thumbs_up_resumes_once(self):
        g = Gestures()
        pose = hand((False, False, False, False))
        pose[4].y = 0.4
        g.update(pose, 0)
        self.assertEqual(g.update(pose, 0.7), ('play', None))
        self.assertIsNone(g.update(pose, 1.5))

    def test_palm_pauses_once_until_released(self):
        g = Gestures()
        self.assertIsNone(g.update(hand(), 0))
        self.assertEqual(g.update(hand(), 0.9), ('pause', None))
        self.assertIsNone(g.update(hand(), 1.5))
        g.update(None, 2)
        g.update(hand(), 3)
        self.assertEqual(g.update(hand(), 4), ('pause', None))

    def test_swipe_does_not_pause_or_repeat_immediately(self):
        g = Gestures()
        g.update(hand(), 0)
        self.assertEqual(g.update(hand(shift=-0.3), 0.2), ('next', None))
        self.assertIsNone(g.update(hand(shift=-0.4), 0.3))
        self.assertIsNone(g.update(hand(shift=-0.4), 1.3))

    def test_slow_swipe_with_one_folded_finger(self):
        g = Gestures()
        g.update(hand((True, True, True, False)), 0)
        self.assertIsNone(g.update(hand((True, True, True, False), -0.08), 0.3))
        self.assertEqual(g.update(hand((True, True, True, False), -0.17), 0.7), ('next', None))

    def test_swipe_survives_short_pose_flicker(self):
        g = Gestures()
        g.update(hand(), 0)
        g.update(hand(shift=0.08), 0.2)
        g.update(hand((True, True, False, False), 0.1), 0.25)
        self.assertEqual(g.update(hand(shift=0.17), 0.35), ('previous', None))

    def test_swipe_requires_reset_and_vertical_motion_does_not_skip(self):
        g = Gestures()
        g.update(hand(), 0)
        self.assertEqual(g.update(hand(shift=-0.2), 0.4), ('next', None))
        self.assertIsNone(g.update(hand(shift=0.3), 2))
        g.update(hand((False, False, False, False)), 2.1)
        g.update(hand((False, False, False, False)), 2.3)
        g.update(hand(), 2.4)
        self.assertEqual(g.update(hand(shift=0.2), 2.8), ('previous', None))
        g = Gestures()
        g.update(hand(), 0)
        vertical = hand(shift=0.15)
        for point in vertical:
            point.y += 0.25
        self.assertIsNone(g.update(vertical, 0.4))

    def test_two_fingers_increase_with_hold_and_repeat_delay(self):
        g = Gestures()
        pose = hand((True, True, False, False))
        self.assertIsNone(g.update(pose, 0, 40))
        self.assertIsNone(g.update(pose, 0.4, 40))
        self.assertEqual(g.update(pose, 0.7, 40), ('volume_step', 5))
        self.assertIsNone(g.update(pose, 0.9, 45))
        self.assertEqual(g.update(pose, 1.6, 45), ('volume_step', 5))

    def test_one_finger_decreases_and_direction_change_requires_hold(self):
        g = Gestures()
        up, down = hand((True, True, False, False)), hand((True, False, False, False))
        g.update(up, 0, 40)
        self.assertEqual(g.update(up, 0.7, 40), ('volume_step', 5))
        self.assertIsNone(g.update(down, 0.8, 45))
        self.assertEqual(g.update(down, 1.6, 45), ('volume_step', -5))

    def test_volume_limits_missing_state_and_hand_loss(self):
        g = Gestures()
        up = hand((True, True, False, False))
        g.update(up, 0, 100)
        self.assertIsNone(g.update(up, 1, 100))
        self.assertIsNone(g.update(None, 2, 50))
        self.assertIsNone(g.update(up, 3, 50))
        self.assertEqual(g.update(up, 3.7, 50), ('volume_step', 5))
        g.update(up, 4, None)
        self.assertIsNone(g.update(up, 5, None))


class SpotifyTests(unittest.TestCase):
    def library_worker(self):
        worker = PlaybackWorker.__new__(PlaybackWorker)
        worker.lock = threading.Lock()
        worker.state = {}
        worker.client = self.client()
        return worker

    def test_playlist_pagination_and_null_entries(self):
        worker = self.library_worker()
        with patch.object(worker.client,'api',return_value={
                'items':[None,{'id':'abc','name':'Focus'}], 'offset':50,'total':51}) as request:
            worker.load_library(50)
        self.assertIn('offset=50',request.call_args.args[1])
        self.assertEqual(len(worker.state['playlists']),1)
        self.assertFalse(worker.state['library_loading'])

    def test_playlist_items_preserve_positions_and_unavailable_rows(self):
        worker = self.library_worker()
        with patch.object(worker.client,'api',return_value={'items':[
                {'item':{'uri':'spotify:track:one','name':'One'}}, None,
                {'track':{'uri':'spotify:track:two','is_playable':False}}], 'total':53}):
            worker.load_tracks({'playlist':{'id':'abc'},'offset':50})
        rows = worker.state['tracks']
        self.assertEqual([r['position'] for r in rows],[50,51,52])
        self.assertEqual([r['playable'] for r in rows],[True,False,False])
        self.assertFalse(worker.state['tracks_loading'])

    def test_library_access_error_is_visible_and_clears_loading(self):
        worker = self.library_worker()
        with patch.object(worker.client,'api',side_effect=SpotifyError('Denied')):
            worker.load_tracks({'playlist':{'id':'abc'}})
        self.assertIn('Reconnect',worker.state['library_message'])
        self.assertFalse(worker.state['tracks_loading'])

    def test_playlist_endpoint_and_play_context_body(self):
        client = self.client()
        with patch('spotify_client.urlopen',return_value=io.BytesIO(b'{}')) as request:
            client.api('GET','/me/playlists?limit=50')
            self.assertEqual(request.call_args.args[0].full_url,'https://api.spotify.com/v1/me/playlists?limit=50')
        body = {'context_uri':'spotify:playlist:abc','offset':{'position':51}}
        with patch('spotify_client.urlopen',return_value=io.BytesIO(b'')) as request:
            client.api('PUT','/play',body=body)
            self.assertEqual(json.loads(request.call_args.args[0].data),body)

    def test_manual_commands_wait_longer_and_require_login(self):
        worker = PlaybackWorker.__new__(PlaybackWorker)
        worker.lock = threading.Lock()
        worker.commands = queue.Queue(maxsize=4)
        worker.state = {'busy': False, 'message': ''}
        worker.client = SpotifyClient('test-client')
        worker.submit('next', manual=True)
        self.assertTrue(worker.commands.empty())
        self.assertIn('Connect Spotify first', worker.snapshot()['message'])
        worker.client.access_token = 'test-token'
        worker.submit('next', manual=True)
        self.assertEqual(worker.commands.get_nowait()[3], 30)
        worker.submit('next')
        self.assertEqual(worker.commands.get_nowait()[3], 2)

    def test_error_messages_distinguish_timeout_dns_and_port_conflict(self):
        self.assertIn('timed out', describe_error(URLError(TimeoutError())))
        self.assertIn('DNS', describe_error(URLError(socket.gaierror())))
        self.assertIn('port 8888 is busy', describe_error(OSError(98, 'occupied')))
        self.assertNotIn('private-token', describe_error(ValueError('private-token')))

    def test_successful_poll_clears_stale_network_warning(self):
        worker = PlaybackWorker.__new__(PlaybackWorker)
        worker.lock = threading.Lock()
        worker.state = {'message': 'Old network error'}
        worker.recovering = True
        worker.art_url = None
        worker.client = self.client()
        with patch.object(worker.client, 'api', return_value={}):
            worker.poll()
        self.assertIn('Connected', worker.snapshot()['message'])
        self.assertFalse(worker.recovering)

    def test_refresh_preserves_previous_refresh_token(self):
        client = self.client()
        client.refresh_token = 'old-refresh'
        with patch('spotify_client.urlopen', return_value=io.BytesIO(
                b'{"access_token":"new-token","expires_in":3600}')):
            client.token({'grant_type': 'refresh_token', 'refresh_token': client.refresh_token})
        self.assertEqual(client.refresh_token, 'old-refresh')
        self.assertEqual(client.access_token, 'new-token')

    def test_pkce_rfc_vector(self):
        self.assertEqual(pkce_challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),
                         'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')

    def client(self):
        client = SpotifyClient('test-client')
        client.access_token = 'test-token'
        client.expires = time.monotonic()+1000
        return client

    def test_empty_playback_is_valid(self):
        with patch('spotify_client.urlopen', return_value=io.BytesIO(b'')):
            self.assertIsNone(self.client().api('GET', ''))

    def test_rate_limit_blocks_followup(self):
        client = self.client()
        error = HTTPError('https://api.spotify.com', 429, 'limit', {'Retry-After': '30'}, None)
        with patch('spotify_client.urlopen', side_effect=error) as request:
            with self.assertRaises(SpotifyError):
                client.api('GET', '')
            with self.assertRaises(SpotifyError):
                client.api('GET', '')
            self.assertEqual(request.call_count, 1)

    def test_volume_request_and_authorization(self):
        with patch('spotify_client.urlopen', return_value=io.BytesIO(b'')) as request:
            self.client().api('PUT', '/volume?volume_percent=40')
            sent = request.call_args.args[0]
            self.assertEqual(sent.get_method(), 'PUT')
            self.assertEqual(sent.get_header('Authorization'), 'Bearer test-token')
            self.assertTrue(sent.full_url.endswith('volume_percent=40'))


if __name__ == '__main__':
    unittest.main()
