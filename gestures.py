"""Temporal gesture interpretation, independent of webcam and Spotify."""
from collections import deque
import math


class Gestures:
    def __init__(self):
        self.path = deque()
        self.pose = None
        self.since = 0
        self.fired = False
        self.cooldown = 0
        self.volume_sent = -1.0
        self.last_seen = None
        self.palm_exit_since = None
        self.swipe_fired = False
        self.label = 'Show one hand'
        self.progress = 0

    def update(self, hand, now, current_volume=None, aspect_ratio=1.0):
        self.progress = 0
        if hand is None:
            if self.pose == 'pause' and self.last_seen is not None and now-self.last_seen < 0.18:
                self.label = 'Keep your open hand in view'
                self.since = now
                return None
            self.path.clear()
            self.pose = None
            self.fired = False
            self.swipe_fired = False
            self.palm_exit_since = None
            self.label = 'Show one hand'
            return None
        self.last_seen = now
        def distance(a, b):
            return math.sqrt(sum((getattr(hand[a], axis) - getattr(hand[b], axis)) ** 2 for axis in ('x', 'y', 'z')))
        up = [distance(t, 0) > distance(t - 2, 0) * 1.14 for t in (8, 12, 16, 20)]
        thumbs_up = not any(up) and hand[4].y < hand[3].y - 0.025 and distance(4, 0) > distance(3, 0) * 1.15
        idx_dx = hand[8].x - hand[5].x
        idx_dy = hand[8].y - hand[5].y
        idx_extended = up[0] or distance(8, 5) > 0.14
        other_curled = not up[1] and not up[2] and not up[3]
        is_pointing_horizontal = idx_extended and other_curled and abs(idx_dx) > 0.08 and abs(idx_dx) > abs(idx_dy) * 0.85

        if is_pointing_horizontal:
            pose = 'point_right' if idx_dx > 0 else 'point_left'
        elif up == [True, True, False, False]:
            pose = 'volume_up'
        elif up == [True, False, False, False]:
            pose = 'volume_down'
        elif thumbs_up:
            pose = 'play'
        elif sum(up) >= 3:
            pose = 'pause'
        else:
            pose = 'neutral'
        # A brief finger-classification flicker must not erase an ongoing swipe.
        if self.pose == 'pause' and pose != 'pause':
            if self.palm_exit_since is None:
                self.palm_exit_since = now
            if now-self.palm_exit_since < 0.15:
                self.since = now
                return None
        else:
            self.palm_exit_since = None
        if pose != self.pose:
            self.pose, self.since, self.fired = pose, now, False
            self.path.clear()
            self.swipe_fired = False
            self.palm_exit_since = None
        if pose in ('point_right', 'point_left'):
            action_name = 'next' if pose == 'point_right' else 'previous'
            self.label = 'Point right: Next song' if pose == 'point_right' else 'Point left: Previous song'
            self.progress = min(1, (now - self.since) / 0.4)
            if now - self.since >= 0.4 and not self.fired and now >= self.cooldown:
                self.fired = True
                self.cooldown = now + 1.0
                self.label = f'Skipped to {action_name} track'
                return (action_name, None)
        elif pose in ('volume_up', 'volume_down'):
            if current_volume is None:
                self.since = now
                self.label = 'Volume unavailable - start Spotify on a supported device'
                return None
            direction = 5 if pose == 'volume_up' else -5
            self.label = 'Two fingers: louder (+5)' if direction > 0 else 'One finger: quieter (-5)'
            self.progress = min(1, (now-self.since)/0.6)
            if now-self.since >= 0.6 and now-self.volume_sent >= 0.8:
                self.volume_sent = now
                if (direction > 0 and current_volume < 100) or (direction < 0 and current_volume > 0):
                    return ('volume_step', direction)
        elif pose == 'pause':
            if self.swipe_fired:
                self.label = 'Swipe sent - close your hand to reset'
                return None
            self.path.append((now, hand[9].x, hand[9].y))
            while self.path and now - self.path[0][0] > 0.9:
                self.path.popleft()
            if len(self.path) > 1:
                start = self.path[0]
                dx, dy = hand[9].x - start[1], hand[9].y - start[2]
                horizontal = abs(dx) > 0.14 and abs(dx) > abs(dy)*1.3
                if horizontal and now >= self.cooldown:
                    self.cooldown, self.fired = now + 1.2, True
                    self.swipe_fired = True
                    self.label = 'Next track detected' if dx < 0 else 'Previous track detected'
                    return ('next' if dx < 0 else 'previous', None)
                # Motion delays pause, so a slow swipe cannot pause mid-gesture.
                if abs(dx) > 0.04 or abs(dy) > 0.04:
                    self.since = now
            self.label = 'Hold palm: pause / swipe: tracks'
            self.progress = min(1, (now - self.since) / 0.8)
            if now - self.since >= 0.8 and not self.fired and now >= self.cooldown:
                self.fired = True
                return ('pause', None)
        elif pose == 'play':
            self.label = 'Hold thumbs-up: resume'
            self.progress = min(1, (now - self.since) / 0.6)
            if now - self.since >= 0.6 and not self.fired and now >= self.cooldown:
                self.fired = True
                return ('play', None)
        else:
            self.label = 'Two fingers: louder. One finger: quieter.'
        return None
