"""Air Music desktop dashboard. Artwork is displayed uncropped and unmodified."""
from pathlib import Path
import math
import random
import time
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


class SmoothDraw:
    """Draw in logical coordinates on a supersampled surface."""
    def __init__(self, image, scale):
        self.draw = ImageDraw.Draw(image)
        self.scale = scale

    def coords(self, points):
        return tuple(round(value * self.scale) for value in points)

    def rounded_rectangle(self, rect, radius=0, **kwargs):
        self.draw.rounded_rectangle(self.coords(rect), radius=round(radius*self.scale), **kwargs)

    def rectangle(self, rect, **kwargs):
        self.draw.rectangle(self.coords(rect), **kwargs)

    def ellipse(self, rect, width=1, **kwargs):
        self.draw.ellipse(self.coords(rect), width=max(1, round(width*self.scale)), **kwargs)

    def polygon(self, points, **kwargs):
        scaled = [tuple(round(v * self.scale) for v in pt) for pt in points]
        self.draw.polygon(scaled, **kwargs)

    def line(self, points, **kwargs):
        scaled = [tuple(round(v * self.scale) for v in pt) for pt in points]
        self.draw.line(scaled, **kwargs)

    def text(self, position, value, **kwargs):
        self.draw.text(self.coords(position), value, **kwargs)

    def textlength(self, value, **kwargs):
        return self.draw.textlength(value, **kwargs) / self.scale


class MusicUI:
    """Premium dark theme with glass panels, gradient accents, and smooth animations."""

    # --- Color palette ---
    BG = '#0a0a12'
    PANEL = '#121220'
    PANEL_BORDER = '#2a2a3e'
    HOVER = '#1e1e32'
    ACTIVE_ROW = '#162a1e'
    PRIMARY = '#e8e8f0'
    MUTED = '#7878a0'
    ACCENT = '#1ed760'
    ACCENT_DARK = '#17a84a'
    ACCENT_GLOW = '#0a3020'
    BTN = '#1a1a30'
    BTN_HOVER = '#262640'
    SEPARATOR = '#222238'
    PLAYBACK_BG = '#0e0e1a'
    PROGRESS_BG = '#2a2a3e'
    CARD = '#1a1a2c'
    CARD_BORDER = '#282840'
    TOPBAR = '#0e0e1a'
    PLAYLIST_COLORS = ['#1e3a5e', '#3a1e5e', '#5e3a1e', '#1e5e3a', '#5e1e3a']
    VOLUME_TRACK = '#2a2a3e'
    VOLUME_FILL = '#1ed760'
    VOLUME_KNOB = '#e8e8f0'

    def __init__(self):
        self.actions, self.buttons = [], []
        self.hovered = None
        self.library_scroll = self.track_scroll = 0
        self.library_count = self.track_count = 0
        self.list_key = None
        self.fonts = {}
        self.output_scale = 1.0
        self.font_scale = None
        self.prepare_fonts(1.0)
        self._chrome = None
        self._chrome_scale = None
        self._art_cache = {}
        self._smooth_progress = 0.0
        # Continuous playback progress interpolation
        self._last_progress_ms = 0
        self._last_progress_time = 0.0
        self._last_track_uri = None
        self._last_is_playing = False
        # Animated equalizer bars
        self._eq_bars = [random.random() for _ in range(4)]
        self._eq_targets = [random.random() for _ in range(4)]
        self._eq_last_update = 0.0
        # Volume slider drag state
        self._volume_dragging = False

    def set_viewport(self, width, height):
        # Keep controls usable on small windows while allowing large displays to
        # take advantage of the available space.
        self.output_scale = max(0.5, min(width / 1200, height / 800, 3.0))

    def prepare_fonts(self, scale):
        if self.font_scale == scale:
            return
        self.font_scale = scale
        for size in (11, 12, 14, 16, 20, 28, 34):
            font = Path('C:/Windows/Fonts/segoeui.ttf')
            self.fonts[size] = (ImageFont.truetype(str(font), round(size * scale))
                                if font.exists()
                                else ImageFont.load_default(size=round(size * scale)))

    def _build_chrome(self, scale):
        """Pre-render static backgrounds, panel fills, and panel borders."""
        w, h = round(1200 * scale), round(800 * scale)
        img = Image.new('RGB', (w, h), self.BG)
        d = SmoothDraw(img, scale)
        # Top bar
        d.rectangle((0, 0, 1200, 70), fill=self.TOPBAR)
        d.rectangle((0, 69, 1200, 70), fill=self.SEPARATOR)
        # Library panel
        d.rounded_rectangle((12, 76, 232, 680), radius=12, fill=self.PANEL,
                            outline=self.PANEL_BORDER)
        # Track list panel
        d.rounded_rectangle((244, 76, 846, 680), radius=12, fill=self.PANEL,
                            outline=self.PANEL_BORDER)
        # Camera panel
        d.rounded_rectangle((858, 76, 1188, 680), radius=12, fill=self.PANEL,
                            outline=self.PANEL_BORDER)
        # Playback bar
        d.rectangle((0, 710, 1200, 800), fill=self.PLAYBACK_BG)
        d.rectangle((0, 710, 1200, 711), fill=self.PANEL_BORDER)
        return img

    def mouse(self, event, x, y, flags, param):
        x, y = x / self.output_scale, y / self.output_scale
        self.hovered = next((action for rect, action in self.buttons
                             if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]), None)
        if event == cv2.EVENT_MOUSEWHEEL:
            delta = (flags >> 16) & 0xffff
            delta = delta - 65536 if delta > 32767 else delta
            step = -3 if delta > 0 else 3
            if x < 232:
                self.library_scroll = max(0, min(max(0, self.library_count-8), self.library_scroll+step))
            elif x < 846:
                self.track_scroll = max(0, min(max(0, self.track_count-6), self.track_scroll+step))
            return
        # Volume slider interaction
        if 820 <= x <= 1050 and 776 <= y <= 790:
            if event == cv2.EVENT_LBUTTONDOWN:
                self._volume_dragging = True
                vol = max(0, min(100, int((x - 830) / 200 * 100)))
                self.actions.append(('volume_set', vol))
                return
            elif event == cv2.EVENT_MOUSEMOVE and self._volume_dragging:
                vol = max(0, min(100, int((x - 830) / 200 * 100)))
                self.actions.append(('volume_set', vol))
                return
        if event in (cv2.EVENT_LBUTTONUP, cv2.EVENT_MOUSEMOVE) and self._volume_dragging:
            if event == cv2.EVENT_LBUTTONUP:
                self._volume_dragging = False
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            for rect, action in self.buttons:
                if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                    self.actions.append(action)
                    break

    def _interpolate_position(self, playback, item, now_t):
        """Interpolate playback position locally between API polls for silky-smooth progress."""
        raw_ms = playback.get('progress_ms') or 0
        track_uri = item.get('uri', '')
        is_playing = bool(playback.get('is_playing'))

        # Detect state changes (track change, seek, play/pause toggle)
        if track_uri != self._last_track_uri or abs(raw_ms - self._last_progress_ms) > 3000:
            self._last_progress_ms = raw_ms
            self._last_progress_time = now_t
            self._last_track_uri = track_uri
            self._last_is_playing = is_playing
            return raw_ms

        # Update reference point when we get a new API value
        if raw_ms != self._last_progress_ms:
            self._last_progress_ms = raw_ms
            self._last_progress_time = now_t
            self._last_is_playing = is_playing

        if is_playing:
            elapsed = now_t - self._last_progress_time
            total = item.get('duration_ms') or 999999
            return min(self._last_progress_ms + int(elapsed * 1000), total)
        return self._last_progress_ms

    def _update_eq(self, is_playing, now_t):
        """Animate equalizer bar heights for the currently playing track."""
        if now_t - self._eq_last_update > 0.12:
            self._eq_last_update = now_t
            if is_playing:
                self._eq_targets = [0.3 + 0.7 * random.random() for _ in range(4)]
            else:
                self._eq_targets = [0.1 for _ in range(4)]
        # Smooth interpolation toward targets
        for i in range(4):
            self._eq_bars[i] += (self._eq_targets[i] - self._eq_bars[i]) * 0.25

    def render(self, frame, state, gesture, progress, enabled, demo=False):
        scale = self.output_scale
        self.prepare_fonts(scale)

        # Use cached chrome or rebuild on scale change
        if self._chrome is None or self._chrome_scale != scale:
            self._chrome = self._build_chrome(scale)
            self._chrome_scale = scale
        screen = self._chrome.copy()
        d = SmoothDraw(screen, scale)
        self.buttons = []

        now_t = time.monotonic()
        primary, muted, accent = self.PRIMARY, self.MUTED, self.ACCENT

        # Smooth gesture progress for butter-smooth bar animation
        if progress > self._smooth_progress:
            self._smooth_progress += (progress - self._smooth_progress) * 0.35
        elif progress < self._smooth_progress:
            self._smooth_progress = max(0, self._smooth_progress - 0.06)
        if abs(self._smooth_progress) < 0.005:
            self._smooth_progress = 0.0
        display_progress = self._smooth_progress

        # ----- helpers ------------------------------------------------
        def text(x, y, value, size=14, color=muted, width=None):
            value = str(value)
            if width:
                full = value
                while value and d.textlength(value, font=self.fonts[size]) > width:
                    value = value[:-1]
                if value != full:
                    value = value[:-3] + '...'
            d.text((x, y), value, font=self.fonts[size], fill=color)

        def button(rect, label, action, selected=False):
            hovered = self.hovered == action
            if selected:
                fill = accent
            elif hovered:
                fill = self.BTN_HOVER
            else:
                fill = self.BTN
            outline = (self.ACCENT_DARK if selected
                       else (self.PANEL_BORDER if hovered else None))
            d.rounded_rectangle(rect, radius=20, fill=fill, outline=outline)
            text(rect[0]+14, rect[1]+10, label, 14,
                 '#000000' if selected else primary, rect[2]-rect[0]-28)
            self.buttons.append((rect, action))

        def icon_button(rect, icon_type, action, selected=False, radius=None):
            hovered = self.hovered == action
            if selected:
                fill = '#28f070' if hovered else accent
                icon_color = '#000000'
            elif hovered:
                fill = self.BTN_HOVER
                icon_color = '#ffffff'
            else:
                fill = self.BTN
                icon_color = primary
            outline = (self.ACCENT_DARK if selected
                       else (self.PANEL_BORDER if hovered else None))
            btn_radius = radius if radius is not None else round((rect[3] - rect[1]) / 2)
            d.rounded_rectangle(rect, radius=btn_radius, fill=fill, outline=outline)

            cx = (rect[0] + rect[2]) / 2
            cy = (rect[1] + rect[3]) / 2

            if icon_type == 'play':
                # Right-pointing triangle
                d.polygon([(cx - 5, cy - 8), (cx - 5, cy + 8), (cx + 7, cy)], fill=icon_color)
            elif icon_type == 'pause':
                # Two vertical pause bars
                d.rounded_rectangle((cx - 6, cy - 8, cx - 2, cy + 8), radius=1, fill=icon_color)
                d.rounded_rectangle((cx + 2, cy - 8, cx + 6, cy + 8), radius=1, fill=icon_color)
            elif icon_type == 'previous':
                # Bar on left + left-pointing triangle
                d.rounded_rectangle((cx - 7, cy - 7, cx - 4, cy + 7), radius=1, fill=icon_color)
                d.polygon([(cx + 6, cy - 7), (cx + 6, cy + 7), (cx - 3, cy)], fill=icon_color)
            elif icon_type == 'next':
                # Right-pointing triangle + bar on right
                d.polygon([(cx - 6, cy - 7), (cx - 6, cy + 7), (cx + 3, cy)], fill=icon_color)
                d.rounded_rectangle((cx + 4, cy - 7, cx + 7, cy + 7), radius=1, fill=icon_color)

            self.buttons.append((rect, action))

        def cover(art, bounds, radius=8):
            x, y, size = bounds
            d.rounded_rectangle((x, y, x+size, y+size), radius=radius,
                                fill=self.ACCENT_GLOW)
            if art is not None:
                cache_key = (id(art), size, round(scale, 2))
                cached = self._art_cache.get(cache_key)
                if cached is None:
                    target = (round(size*scale), round(size*scale))
                    view = ImageOps.contain(art, target, Image.Resampling.BILINEAR)
                    mask = Image.new('L', view.size, 0)
                    ImageDraw.Draw(mask).rounded_rectangle(
                        (0, 0, view.width-1, view.height-1),
                        radius=round(radius*scale), fill=255)
                    cached = (view, mask)
                    if len(self._art_cache) > 20:
                        self._art_cache.clear()
                    self._art_cache[cache_key] = cached
                view, mask = cached
                px = round((x+size/2)*scale) - view.width//2
                py = round((y+size/2)*scale) - view.height//2
                screen.paste(view, (px, py), mask)
            else:
                d.ellipse((x+size*.2, y+size*.2, x+size*.8, y+size*.8),
                          fill='#0e2018', outline=self.ACCENT_DARK, width=2)
                d.ellipse((x+size*.44, y+size*.44, x+size*.56, y+size*.56),
                          fill=accent)

        def duration(ms):
            seconds = max(0, int(ms or 0))//1000
            return f'{seconds//60}:{seconds%60:02d}'

        def draw_equalizer(x, y, bar_width, max_height, is_playing):
            """Draw animated dancing equalizer bars."""
            self._update_eq(is_playing, now_t)
            gap = 2
            for i, h_frac in enumerate(self._eq_bars):
                bx = x + i * (bar_width + gap)
                bar_h = max(2, h_frac * max_height)
                by = y + max_height - bar_h
                d.rounded_rectangle((bx, by, bx + bar_width, y + max_height),
                                    radius=1, fill=accent)

        # ----- state --------------------------------------------------
        playback = state.get('playback') or {}
        item = playback.get('item') or {}
        device = playback.get('device') or {}
        playlists = state.get('playlists') or []
        selected = state.get('selected_playlist') or {}
        rows = state.get('tracks') or []
        key = (selected.get('id'), state.get('tracks_offset', 0))
        if key != self.list_key:
            self.track_scroll, self.list_key = 0, key
        self.library_count, self.track_count = len(playlists), len(rows)
        self.library_scroll = min(self.library_scroll, max(0, len(playlists)-8))
        self.track_scroll = min(self.track_scroll, max(0, len(rows)-6))
        is_playing = bool(playback.get('is_playing'))

        # ===== TOP BAR ================================================
        # Logo with ambient glow
        d.ellipse((16, 14, 56, 54), fill=self.ACCENT_GLOW)
        d.ellipse((20, 18, 52, 50), fill=accent)
        text(29, 21, 'a', 20, '#000000')
        text(64, 18, 'Air Music', 28, primary)
        text(250, 27, 'Music, with a wave of your hand.', 14)
        button((772, 16, 962, 58),
               'Gestures on' if enabled else 'Enable gestures', 'gestures', enabled)
        button((974, 16, 1188, 58),
               'Demo session' if demo else (
                   'Reconnect Spotify' if state.get('connected') else 'Connect Spotify'),
               'connect')

        # ===== LIBRARY PANEL ==========================================
        text(28, 88, 'YOUR LIBRARY', 12)
        button((28, 113, 130, 154), 'Refresh', ('library', 0))
        text(28, 168, 'PLAYLISTS', 11)
        for n, playlist in enumerate(playlists[self.library_scroll:self.library_scroll+8]):
            y = 196 + n*50
            action = ('playlist', {'playlist': playlist, 'offset': 0})
            active = selected.get('id') == playlist.get('id')
            if active:
                d.rounded_rectangle((18, y-4, 226, y+42), radius=8,
                                    fill=self.ACTIVE_ROW, outline=self.PANEL_BORDER)
                # Green accent bar on the left edge
                d.rounded_rectangle((18, y+2, 22, y+36), radius=2, fill=accent)
            elif self.hovered == action:
                d.rounded_rectangle((18, y-4, 226, y+42), radius=8, fill=self.HOVER)
            d.rounded_rectangle((28, y, 64, y+36), radius=6,
                                fill=self.PLAYLIST_COLORS[
                                    (self.library_scroll+n) % len(self.PLAYLIST_COLORS)])
            text(38, y+6, str(self.library_scroll+n+1), 14, primary)
            text(74, y, playlist.get('name', 'Untitled'), 14,
                 accent if active else primary, 142)
            text(74, y+21,
                 (playlist.get('owner') or {}).get('display_name') or 'Playlist',
                 12, width=142)
            self.buttons.append(((18, y-4, 226, y+42), action))
        if not playlists:
            text(28, 210,
                 'Loading...' if state.get('library_loading')
                 else 'Your playlists appear here.', 12, width=186)
        offset = state.get('library_offset', 0)
        if offset:
            button((28, 628, 116, 666), 'Back', ('library', max(0, offset-50)))
        if offset+50 < state.get('library_total', 0):
            button((126, 628, 216, 666), 'More', ('library', offset+50))

        # ===== TRACK LIST PANEL =======================================
        # A richer green-teal header gradient
        for band in range(166):
            t = band / 165
            color = tuple(round(a+(b-a)*t) for a, b in
                          zip((25, 65, 52), (18, 30, 26)))
            d.rectangle((245, 77+band, 845, 78+band), fill=color)
        cover(state.get('playlist_art') if selected else state.get('art'),
              (268, 96, 128), radius=10)
        text(416, 100,
             'DEMO PLAYLIST' if demo else (
                 'PLAYLIST' if selected else 'WELCOME BACK'), 12, primary)
        text(416, 128, selected.get('name') or 'Your music, your way', 28,
             primary, 404)
        owner = ((selected.get('owner') or {}).get('display_name')
                 or 'Select a playlist from your library')
        text(416, 174, owner, 14, '#a8c4b8', 402)
        text(416, 200,
             f'{state.get("tracks_total", 0)} songs' if selected
             else 'Browse songs. Control playback with gestures.',
             12, '#8aab9c', 402)
        if selected:
            button((268, 257, 380, 301), 'Play playlist',
                   ('play_track', {'context_uri': selected.get('uri', ''),
                                   'position': 0}), True)
            url = (selected.get('external_urls') or {}).get('spotify')
            if url:
                button((392, 257, 536, 301), 'Open in Spotify', ('open_url', url))
        else:
            text(268, 265, 'Pick something to listen to', 20, primary)
        text(272, 320, '#', 12)
        text(306, 320, 'TITLE / ARTIST', 12)
        text(607, 320, 'ALBUM', 12)
        text(786, 320, 'TIME', 12)
        d.rectangle((268, 343, 824, 344), fill=self.SEPARATOR)
        for n, row in enumerate(rows[self.track_scroll:self.track_scroll+6]):
            track = row['track']
            y = 354 + n*43
            action = ('play_track', {'context_uri': selected.get('uri', ''),
                                     'position': row['position']})
            active = bool(track.get('uri')) and track.get('uri') == item.get('uri')
            # Alternating subtle row tint for readability
            if n % 2 == 0:
                d.rounded_rectangle((264, y-2, 829, y+39), radius=4,
                                    fill='#14141e')
            if active:
                d.rounded_rectangle((264, y-2, 829, y+39), radius=4,
                                    fill=self.ACTIVE_ROW, outline=self.PANEL_BORDER)
            elif self.hovered == action:
                d.rounded_rectangle((264, y-2, 829, y+39), radius=4,
                                    fill=self.HOVER)
            # Track number or equalizer animation for active track
            if active and is_playing:
                draw_equalizer(272, y+6, 4, 22, True)
            else:
                text(272, y+8, str(row['position']+1), 12,
                     accent if active else muted)
            text(306, y, track.get('name') or 'Unavailable song', 14,
                 accent if active else primary if row.get('playable') else muted,
                 282)
            text(306, y+21,
                 ', '.join(a.get('name', '') for a in track.get('artists', []))
                 or track.get('publisher', ''), 12, width=282)
            text(607, y+9, (track.get('album') or {}).get('name', '?'),
                 12, width=163)
            text(786, y+9, duration(track.get('duration_ms')), 12)
            if row.get('playable'):
                self.buttons.append(((264, y-2, 829, y+39), action))
        if not rows:
            text(272, 375,
                 'Loading songs...' if state.get('tracks_loading')
                 else 'Select a playlist to see its songs.', 16, width=536)
        track_offset = state.get('tracks_offset', 0)
        if selected and track_offset:
            button((268, 621, 354, 660), 'Back',
                   ('playlist', {'playlist': selected,
                                 'offset': max(0, track_offset-50)}))
        if selected and track_offset+50 < state.get('tracks_total', 0):
            button((366, 621, 462, 660), 'More songs',
                   ('playlist', {'playlist': selected,
                                 'offset': track_offset+50}))
        text(488, 635, 'Scroll to browse songs', 12)

        # ===== CAMERA PANEL ===========================================
        text(878, 88, 'Gesture Camera', 20, primary)
        # Pulsing status indicator
        if enabled:
            pulse = 0.5 + 0.5 * math.sin(now_t * 4)
            gr = 8 + 3 * pulse
            d.ellipse((1160-gr, 105-gr, 1160+gr, 105+gr),
                      fill=self.ACCENT_GLOW)
            d.ellipse((1155, 100, 1170, 115), fill=accent)
        else:
            d.ellipse((1155, 100, 1170, 115), fill=muted)
        # Camera frame with subtle border
        d.rounded_rectangle((873, 128, 1173, 376), radius=8,
                            fill='#0a0a14', outline=self.PANEL_BORDER)
        # Fast OpenCV camera resize preserving aspect ratio without distortion
        max_w, max_h = round(296 * scale), round(244 * scale)
        fh, fw = frame.shape[:2]
        ratio = min(max_w / max(1, fw), max_h / max(1, fh))
        nw, nh = max(1, round(fw * ratio)), max(1, round(fh * ratio))
        cam_resized = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                                 (nw, nh), interpolation=cv2.INTER_LINEAR)
        view = Image.fromarray(cam_resized)
        screen.paste(view, (round(1023*scale) - nw//2,
                            round(252*scale) - nh//2))
        text(878, 388,
             'LIVE CONTROL' if enabled else 'GESTURES DISABLED',
             12, accent if enabled else muted)
        text(878, 411,
             gesture if enabled else 'Enable gestures to begin',
             14, primary, 292)
        # Hold-progress bar with glow effect
        d.rounded_rectangle((878, 442, 1168, 448), radius=3, fill=self.PROGRESS_BG)
        if display_progress > 0:
            bar_w = int(290 * min(display_progress, 1))
            # Glow behind the bar
            d.rounded_rectangle((876, 440, 880+bar_w, 450), radius=4,
                                fill=self.ACCENT_GLOW)
            d.rounded_rectangle((878, 442, 878+bar_w, 448), radius=3,
                                fill=accent)
        # Gesture hint cards
        for n, (title, hint) in enumerate([
                ('Point right / left', 'Next / previous song'),
                ('Two fingers / one finger', 'Volume up / down'),
                ('Open palm / thumbs-up', 'Pause / resume')]):
            y = 468 + n*60
            d.rounded_rectangle((870, y, 1178, y+50), radius=8,
                                fill=self.CARD, outline=self.CARD_BORDER)
            text(882, y+6, title, 14, primary)
            text(882, y+26, hint, 12)
        text(878, 652, 'Close hand after each swipe.', 12)

        # ===== MESSAGES ===============================================
        text(24, 687, state.get('message', ''), 12, width=1152)
        library_message = state.get('library_message', '')
        if library_message:
            text(268, 601, library_message, 12, width=554)

        # ===== PLAYBACK BAR ==========================================
        cover(state.get('art'), (18, 728, 54), radius=6)
        text(86, 733, item.get('name') or 'Nothing playing', 14, primary, 265)
        text(86, 756,
             ', '.join(a.get('name', '') for a in item.get('artists', []))
             or 'Start a song in Spotify', 12, width=265)
        self.buttons.append(((18, 728, 351, 785), 'open_track'))

        # Playback controls
        icon_button((472, 722, 520, 762), 'previous', 'previous')
        icon_button((532, 718, 580, 766), 'pause' if is_playing else 'play', 'toggle', selected=True, radius=24)
        icon_button((592, 722, 640, 762), 'next', 'next')

        # Continuous interpolated progress bar
        position = self._interpolate_position(playback, item, now_t)
        total = item.get('duration_ms') or 0
        text(376, 772, duration(position), 12)
        d.rounded_rectangle((420, 779, 694, 783), radius=2, fill=self.PROGRESS_BG)
        if total and position:
            pw = int(274 * min(1, position/total))
            # Playback progress glow
            d.rounded_rectangle((418, 777, 422+pw, 785), radius=3,
                                fill=self.ACCENT_GLOW)
            d.rounded_rectangle((420, 779, 420+pw, 783), radius=2, fill=accent)
        text(708, 772, duration(total), 12)

        # Active device name and equalizer
        text(820, 730, device.get('name') or 'No active device', 12, width=230)
        if is_playing:
            draw_equalizer(820, 750, 3, 14, True)
        text(842, 750, 'Playing' if is_playing else 'Paused', 12,
             accent if is_playing else muted)

        # Volume slider
        volume = device.get('volume_percent')
        if volume is not None:
            # Volume icon
            d.polygon([(822, 775), (828, 775), (835, 770), (835, 785), (828, 780), (822, 780)],
                      fill=muted)
            # Slider track
            d.rounded_rectangle((842, 780, 1042, 784), radius=2, fill=self.VOLUME_TRACK)
            # Filled portion
            fill_w = int(200 * volume / 100)
            if fill_w > 0:
                d.rounded_rectangle((842, 780, 842 + fill_w, 784), radius=2,
                                    fill=self.VOLUME_FILL)
            # Knob
            knob_x = 842 + fill_w
            d.ellipse((knob_x - 5, 778, knob_x + 5, 788), fill=self.VOLUME_KNOB)
            # Percentage label
            text(1050, 775, f'{volume}%', 12, primary)
        else:
            text(820, 775, 'Volume --', 12)

        # ===== FINAL RESIZE (cv2 is much faster than PIL Lanczos) =====
        arr = cv2.cvtColor(np.asarray(screen), cv2.COLOR_RGB2BGR)
        tw = round(1200 * self.output_scale)
        th = round(800 * self.output_scale)
        if arr.shape[1] != tw or arr.shape[0] != th:
            arr = cv2.resize(arr, (tw, th), interpolation=cv2.INTER_AREA)
        return arr
