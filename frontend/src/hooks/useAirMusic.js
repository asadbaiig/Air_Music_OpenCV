import { useState, useEffect, useRef, useCallback } from 'react';

const isBrowser = typeof window !== 'undefined';
const host = isBrowser && window.location.host ? window.location.host : '127.0.0.1:8000';
const protocol = isBrowser && window.location.protocol === 'https:' ? 'https:' : 'http:';
const wsProtocol = isBrowser && window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const API_BASE = `${protocol}//${host}`;
const WS_URL = `${wsProtocol}//${host}/ws`;

export function useAirMusic() {
  const [state, setState] = useState({
    connected: false,
    demo: true,
    message: '',
    playlists: [],
    selected_playlist: null,
    tracks: [],
    playback: {
      is_playing: false,
      progress_ms: 0,
      item: null,
      device: { name: 'Device', volume_percent: 50 },
    },
    gestures_enabled: true,
    gesture_label: 'Ready for gesture',
    gesture_progress: 0,
  });

  const [lastGestureToast, setLastGestureToast] = useState(null);
  const [interpolatedProgress, setInterpolatedProgress] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);

  const wsRef = useRef(null);
  const lastStateRef = useRef(state);
  const lastTimeRef = useRef(Date.now());
  const toastTimeoutRef = useRef(null);

  // Send action via WebSocket or REST fallback
  const sendAction = useCallback((action, value = null) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action, value }));
    } else {
      fetch(`${API_BASE}/api/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      }).catch((err) => console.error('Failed to post action:', err));
    }
  }, []);

  // Fetch initial REST snapshot
  useEffect(() => {
    fetch(`${API_BASE}/api/state`)
      .then((res) => res.json())
      .then((data) => {
        if (data && !data.error) {
          setState((prev) => ({ ...prev, ...data }));
          lastStateRef.current = data;
          setInterpolatedProgress(data.playback?.progress_ms || 0);
        }
      })
      .catch(() => {});
  }, []);

  // Setup WebSocket connection with auto-reconnect
  useEffect(() => {
    let reconnectTimer;
    let isSubscribed = true;

    function connect() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isSubscribed) setWsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'state') {
            const nextState = payload.data;
            setState(nextState);
            lastStateRef.current = nextState;
            lastTimeRef.current = Date.now();

            // Detect trigger gestures for HUD toast
            const label = nextState.gesture_label;
            if (label && label !== 'Ready for gesture' && label !== 'Hold...' && label !== 'None') {
              setLastGestureToast(label);
              if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
              toastTimeoutRef.current = setTimeout(() => {
                setLastGestureToast(null);
              }, 2200);
            }
          }
        } catch (e) {
          console.error('Error parsing WebSocket message:', e);
        }
      };

      ws.onclose = () => {
        if (isSubscribed) {
          setWsConnected(false);
          reconnectTimer = setTimeout(connect, 1500);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      isSubscribed = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  // Smooth local playback progress timer (60fps)
  useEffect(() => {
    const interval = setInterval(() => {
      const curr = lastStateRef.current;
      const isPlaying = curr.playback?.is_playing;
      const duration = curr.playback?.item?.duration_ms || 999999;
      const baseProgress = curr.playback?.progress_ms || 0;

      if (isPlaying) {
        const elapsed = Date.now() - lastTimeRef.current;
        setInterpolatedProgress(Math.min(baseProgress + elapsed, duration));
      } else {
        setInterpolatedProgress(baseProgress);
      }
    }, 100);

    return () => clearInterval(interval);
  }, []);

  return {
    state,
    wsConnected,
    interpolatedProgress,
    lastGestureToast,
    sendAction,
  };
}
