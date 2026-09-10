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
        self.volume_since = None
        self.last_volume = None
        self.volume_sent = 0
        self.label = 'Show one hand'
        self.progress = 0

    def update(self, hand, now):
        self.progress = 0
        if hand is None:
            self.path.clear()
            self.pose = self.volume_since = None
            self.fired = False
            self.last_volume = None
            self.label = 'Show one hand'
            return None
        def distance(a, b):
            return math.sqrt(sum((getattr(hand[a], axis) - getattr(hand[b], axis)) ** 2 for axis in ('x', 'y', 'z')))
        up = [distance(t, 0) > distance(t - 2, 0) * 1.14 for t in (8, 12, 16, 20)]
        palm = max(distance(0, 9), 0.03)
        # Fold ring and little fingers to distinguish volume from an open palm.
        volume_pose = not up[2] and not up[3] and (up[0] or distance(4, 8) / palm < 0.35)
        thumbs_up = not any(up) and hand[4].y < hand[3].y - 0.025 and distance(4, 0) > distance(3, 0) * 1.15
        if thumbs_up:
            pose = 'play'
        elif volume_pose:
            pose = 'volume'
        elif all(up):
            pose = 'pause'
        else:
            pose = 'neutral'
        if pose != self.pose:
            self.pose, self.since, self.fired = pose, now, False
            self.path.clear()
        if pose == 'volume':
            self.label = 'Pinch / spread: volume'
            self.progress = min(1, (now - self.since) / 0.5)
            value = round(max(0, min(1, (distance(4, 8) / palm - 0.15) / 1.05)) * 100)
            if now - self.since >= 0.5 and now - self.volume_sent >= 0.65:
                if self.last_volume is None or abs(value - self.last_volume) >= 5:
                    self.last_volume, self.volume_sent = value, now
                    return ('volume', value)
        elif pose == 'pause':
            self.path.append((now, hand[9].x, hand[9].y))
            while self.path and now - self.path[0][0] > 0.45:
                self.path.popleft()
            if len(self.path) > 1:
                start = self.path[0]
                dx, dy = hand[9].x - start[1], hand[9].y - start[2]
                if abs(dx) > 0.22 and abs(dy) < 0.15 and now >= self.cooldown:
                    self.cooldown, self.fired = now + 1.2, True
                    self.label = 'Next track' if dx < 0 else 'Previous track'
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
            self.label = 'Ready for a gesture'
        return None
