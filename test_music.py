import io
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from gestures import Gestures
from spotify_client import SpotifyClient, SpotifyError, pkce_challenge
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

    def test_volume_requires_hold_and_is_bounded(self):
        g = Gestures()
        pose = hand((True, False, False, False))
        self.assertIsNone(g.update(pose, 0))
        action, volume = g.update(pose, 0.7)
        self.assertEqual(action, 'volume')
        self.assertTrue(0 <= volume <= 100)
        self.assertIsNone(g.update(pose, 0.8))


class SpotifyTests(unittest.TestCase):
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
