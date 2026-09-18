# Handsfree

<p align="center">
  <img src="handsfree_logo.jpg" alt="Handsfree Logo" width="220" style="border-radius: 28px; box-shadow: 0 10px 36px rgba(30, 215, 96, 0.45);" />
  <br />
  <em>Touchless, Gesture-Controlled Spotify Player powered by OpenCV & MediaPipe Computer Vision</em>
</p>

---

## Overview

**Handsfree** is a futuristic, touchless music remote for Spotify. Using standard webcam vision via OpenCV and Google MediaPipe hand landmark detection, Handsfree lets you seamlessly command playback, navigate tracks, and adjust volume completely in mid-air with zero physical contact.

Handsfree offers two premium interfaces:
1. **Modern React Web Dashboard** (`python server.py`): A Spotify-grade dark glassmorphism web experience with live camera HUD stream, real-time WebSocket state synchronization, and reactive gesture toasts.
2. **Native OpenCV Desktop Dashboard** (`python air_music.py`): A dedicated low-latency desktop interface with smooth DPI-aware rendering and interactive controls.

---

## Gestures & Controls

Face one hand toward your webcam (preview is mirrored for natural interaction):

| Gesture | Action | Description |
| :--- | :--- | :--- |
| 👉 **Point Index Right** | **Next Track** | Hold pointing right for 0.4s |
| 👈 **Point Index Left** | **Previous Track** | Hold pointing left for 0.4s |
| ✌️ **Two Fingers Up (V-Sign)** | **Volume Up** | Hold to step volume up (+5%) |
| ☝️ **One Finger Up (Index)** | **Volume Down** | Hold to step volume down (-5%) |
| ✋ **Open Palm** | **Pause** | Hold open palm still for 0.8s |
| 👍 **Thumbs-Up** | **Play / Resume** | Hold thumbs-up for 0.6s |
| 🖐️ **Swipe Palm Left / Right** | **Next / Prev Track** | Rapid mid-air hand swipe across frame |

---

## Quickstart

### 1. Installation
Install with Python 3.11:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item spotify_config.example.json spotify_config.json
# Add your Spotify Client ID in spotify_config.json
```

### 2. Launch the Modern Web Experience (Recommended)
```powershell
.\.venv\Scripts\python.exe server.py
```
> Automatically launches the modern React dashboard at `http://localhost:8000` with the live camera vision HUD, active playlist selector, and playback controls.

### 3. Launch Native Desktop App
```powershell
.\.venv\Scripts\python.exe air_music.py
```

### 4. Try Demo Mode (No Spotify Account Required)
```powershell
.\.venv\Scripts\python.exe server.py --demo
# or desktop:
.\.venv\Scripts\python.exe air_music.py --demo
```

---

## Spotify Setup

1. Create a free Spotify developer application at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Add `http://127.0.0.1:8888/callback` as an **Authorized Redirect URI**.
3. Place your Client ID into `spotify_config.json` (or set the `SPOTIFY_CLIENT_ID` environment variable).
4. Click **Connect Spotify** in the Handsfree interface. Complete the browser login once, and your session will securely persist with automatic silent token refresh.

---

## Automated Tests

Run the test suite to verify gesture detectors and playback state:
```powershell
.\.venv\Scripts\python.exe -m unittest -v
```
