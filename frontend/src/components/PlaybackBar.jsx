import React from 'react';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  Laptop,
  Disc,
} from 'lucide-react';

function formatDuration(ms) {
  const totalSec = Math.max(0, Math.floor((ms || 0) / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${sec < 10 ? '0' : ''}${sec}`;
}

export function PlaybackBar({ state, progressMs, onAction }) {
  const { playback } = state;
  const item = playback?.item || {};
  const isPlaying = playback?.is_playing || false;
  const durationMs = item.duration_ms || 180000;
  const volumePercent = playback?.device?.volume_percent ?? 50;

  const progressFraction = Math.min(1, Math.max(0, progressMs / durationMs));

  const handleSeek = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const fraction = Math.max(0, Math.min(1, clickX / rect.width));
    onAction('seek', Math.floor(fraction * durationMs));
  };

  const handleVolumeChange = (e) => {
    const vol = parseInt(e.target.value, 10);
    onAction('volume', vol);
  };

  return (
    <footer className="playback-bar">
      {/* Current Track Info */}
      <div className="current-track-card">
        <div className="current-track-art">
          {item.album?.images?.[0]?.url ? (
            <img src={item.album.images[0].url} alt="Album Art" />
          ) : (
            <Disc size={28} />
          )}
        </div>
        <div className="current-track-info">
          <span className="current-track-name">{item.name || 'No track selected'}</span>
          <span className="current-track-artist">
            {(item.artists || []).map((a) => a.name).join(', ') || 'Choose a song to play'}
          </span>
        </div>
      </div>

      {/* Main Playback Controls & Scrubber */}
      <div className="playback-center">
        <div className="controls-row">
          <button
            className="control-btn"
            title="Previous track"
            onClick={() => onAction('previous')}
          >
            <SkipBack size={20} />
          </button>

          <button
            className="control-btn control-btn-play"
            title={isPlaying ? 'Pause' : 'Play'}
            onClick={() => onAction('toggle')}
          >
            {isPlaying ? <Pause size={20} fill="#000" /> : <Play size={20} fill="#000" style={{ marginLeft: '2px' }} />}
          </button>

          <button
            className="control-btn"
            title="Next track"
            onClick={() => onAction('next')}
          >
            <SkipForward size={20} />
          </button>
        </div>

        <div className="progress-row">
          <span className="time-label">{formatDuration(progressMs)}</span>
          <div className="progress-scrubber" onClick={handleSeek}>
            <div
              className="progress-scrubber-fill"
              style={{ width: `${progressFraction * 100}%` }}
            />
          </div>
          <span className="time-label right">{formatDuration(durationMs)}</span>
        </div>
      </div>

      {/* Volume & Device Status */}
      <div className="playback-right">
        <div className="device-indicator">
          <Laptop size={15} color="var(--spotify-green)" />
          <span>{playback?.device?.name || 'Local Player'}</span>
        </div>

        <div className="volume-control">
          <button
            className="control-btn"
            onClick={() => onAction('volume', volumePercent > 0 ? 0 : 50)}
          >
            {volumePercent > 0 ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
          <input
            type="range"
            min="0"
            max="100"
            value={volumePercent}
            onChange={handleVolumeChange}
            className="volume-slider"
          />
        </div>
      </div>
    </footer>
  );
}
