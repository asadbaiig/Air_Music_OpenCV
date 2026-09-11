"""Air Music desktop dashboard. Artwork is displayed uncropped and unmodified."""
from pathlib import Path
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

    def text(self, position, value, **kwargs):
        self.draw.text(self.coords(position), value, **kwargs)

    def textlength(self, value, **kwargs):
        return self.draw.textlength(value, **kwargs) / self.scale


class MusicUI:
    def __init__(self):
        self.actions, self.buttons = [], []
        self.fonts = {}
        self.output_scale = 1.0
        self.font_scale = None
        self.prepare_fonts(2.0)

    def set_viewport(self, width, height):
        self.output_scale = max(0.5, min(width / 1200, height / 800, 3.0))

    def prepare_fonts(self, scale):
        if self.font_scale == scale:
            return
        self.font_scale = scale
        for size in (12, 14, 16, 20, 28, 34):
            font = Path('C:/Windows/Fonts/segoeui.ttf')
            self.fonts[size] = ImageFont.truetype(str(font), round(size*scale)) if font.exists() else ImageFont.load_default(size=round(size*scale))

    def mouse(self, event, x, y, flags, param):
        x, y = x / self.output_scale, y / self.output_scale
        if event == cv2.EVENT_LBUTTONDOWN:
            for rect, action in self.buttons:
                if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                    self.actions.append(action)
                    break

    def render(self, frame, state, gesture, progress, enabled, demo=False):
        scale = self.output_scale * 2
        self.prepare_fonts(scale)
        screen = Image.new('RGB', (round(1200*scale), round(800*scale)), '#0b1018')
        d = SmoothDraw(screen, scale)
        self.buttons = []
        def text(x, y, value, size=14, color='#a2aec0', max_width=None):
            value = str(value)
            if max_width:
                original = value
                while value and d.textlength(value, font=self.fonts[size]) > max_width:
                    value = value[:-1]
                if value != original:
                    value = value[:-3] + '...'
            d.text((x, y), value, fill=color, font=self.fonts[size])

        def button(rect, label, action, selected=False):
            d.rounded_rectangle(rect, radius=12, fill='#b9f47e' if selected else '#223044')
            text(rect[0]+16, rect[1]+12, label, 14, '#142113' if selected else '#e8eef7')
            self.buttons.append((rect, action))

        text(30, 22, 'Air Music', 34, '#f2f6fc')
        text(32, 67, 'YOUR MUSIC. A LITTLE MORE HANDS-FREE.', 12)
        button((762, 28, 956, 78), 'Gestures on  G' if enabled else 'Enable gestures  G', 'gestures', enabled)
        button((970, 28, 1170, 78), 'Demo mode' if demo else ('Reconnect  C' if state['connected'] else 'Connect Spotify  C'), 'connect')

        playback = state.get('playback') or {}
        item = playback.get('item') or {}
        device = playback.get('device') or {}
        d.rounded_rectangle((24, 112, 526, 720), radius=22, fill='#151f2d')
        text(48, 135, 'DEMO PREVIEW' if demo else 'NOW PLAYING ON SPOTIFY', 12, '#b9f47e')
        d.rounded_rectangle((100, 179, 450, 529), radius=16, fill='#243447')
        if state.get('art') is not None:
            cover = ImageOps.contain(state['art'], (round(350*scale), round(350*scale)), Image.Resampling.LANCZOS)
            screen.paste(cover, (round(275*scale)-cover.width//2, round(354*scale)-cover.height//2))
        else:
            d.ellipse((187, 266, 363, 442), fill='#0e1927', outline='#526983', width=2)
            d.ellipse((247, 326, 303, 382), fill='#b9f47e')
            text(152, 466, 'Your next listening session', 14)
        text(48, 548, item.get('name') or 'Make room for music', 28, '#f4f7fc', 452)
        artists = ', '.join(a['name'] for a in item.get('artists', [])) or item.get('publisher') or 'Open Spotify and start a song'
        text(48, 587, artists, 16, max_width=452)
        duration = item.get('duration_ms') or 1
        position = playback.get('progress_ms') or 0
        d.rounded_rectangle((48, 626, 498, 631), radius=2, fill='#354354')
        if position:
            d.rounded_rectangle((48, 626, 48+int(450*min(1, position/duration)), 631), radius=2, fill='#b9f47e')
        button((48, 654, 182, 699), 'Previous', 'previous')
        button((193, 654, 353, 699), 'Pause' if playback.get('is_playing') else 'Play', 'toggle', True)
        button((364, 654, 498, 699), 'Next', 'next')

        d.rounded_rectangle((548, 112, 1176, 488), radius=22, fill='#151f2d')
        view = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        view = ImageOps.contain(view, (round(596*scale), round(316*scale)), Image.Resampling.LANCZOS)
        screen.paste(view, (round(862*scale)-view.width//2, round(294*scale)-view.height//2))
        text(568, 455, gesture if enabled else 'Gesture control is off. Click Enable gestures to start.', 14, '#edf4ff', 588)
        if progress > 0:
            d.rectangle((568, 482, 568+int(588*min(progress, 1)), 486), fill='#b9f47e')
        text(552, 509, 'THE CONTROLS', 12, '#b9f47e')
        controls = [('FINGER VOLUME', 'Two fingers: louder. One finger: quieter. Hold to repeat.'),
                    ('SWIPE OPEN PALM', 'Left: next. Right: previous. Close hand to reset.'),
                    ('HOLD OPEN PALM', 'Pause. Hold thumbs-up to resume.')]
        for i, (title, caption) in enumerate(controls):
            y = 539 + 56*i
            text(552, y, title, 12, '#eef4fd')
            text(552, y+20, caption, 14)
        volume = device.get('volume_percent')
        text(552, 713, f'{device.get("name", "No active device")}  /  Volume {volume if volume is not None else "--"}%', 14, max_width=450)
        button((1030, 691, 1094, 735), '- 5', 'quieter')
        button((1106, 691, 1176, 735), '+ 5', 'louder')
        text(32, 753, state.get('message', ''), 14, '#c8d6e8', 1000)
        text(1070, 755, 'Q to exit', 12)
        if item.get('external_urls', {}).get('spotify'):
            self.buttons.append(((100, 179, 450, 529), 'open_track'))
        screen = screen.resize((round(1200*self.output_scale), round(800*self.output_scale)), Image.Resampling.LANCZOS)
        return cv2.cvtColor(np.asarray(screen), cv2.COLOR_RGB2BGR)
