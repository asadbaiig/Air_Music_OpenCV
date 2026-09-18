import React from 'react';
import { useAirMusic } from './hooks/useAirMusic';
import { Navbar } from './components/Navbar';
import { Sidebar } from './components/Sidebar';
import { TrackList } from './components/TrackList';
import { CameraCard } from './components/CameraCard';
import { PlaybackBar } from './components/PlaybackBar';
import { GestureToast } from './components/GestureToast';

export default function App() {
  const {
    state,
    wsConnected,
    interpolatedProgress,
    lastGestureToast,
    sendAction,
  } = useAirMusic();

  return (
    <div className="app-container">
      {/* Background ambient lighting */}
      <div className="ambient-bg">
        <div className="ambient-glow-1" />
        <div className="ambient-glow-2" />
      </div>

      {/* Floating real-time gesture toast */}
      <GestureToast gesture={lastGestureToast} />

      {/* Top Navbar */}
      <Navbar
        state={state}
        wsConnected={wsConnected}
        onAction={sendAction}
      />

      {/* 3-Column Glassmorphic Layout */}
      <div className="main-content">
        <Sidebar
          state={state}
          onAction={sendAction}
        />

        <TrackList
          state={state}
          onAction={sendAction}
        />

        <CameraCard
          state={state}
        />
      </div>

      {/* Bottom Sticky Playback Bar */}
      <PlaybackBar
        state={state}
        progressMs={interpolatedProgress}
        onAction={sendAction}
      />
    </div>
  );
}
