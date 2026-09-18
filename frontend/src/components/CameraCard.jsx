import React from 'react';
import { Camera, Eye, ArrowLeftRight, Volume2, Hand, ThumbsUp } from 'lucide-react';

export function CameraCard({ state }) {
  const { gestures_enabled, gesture_label, gesture_progress } = state;

  return (
    <aside className="panel camera-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Camera size={18} color="var(--spotify-green)" />
          <span className="panel-title">Gesture Vision</span>
        </div>
        <span className={`status-dot ${gestures_enabled ? 'active' : ''}`} />
      </div>

      {/* Live Video Feed */}
      <div className="video-container">
        <img
          src="/api/video_feed"
          alt="Live OpenCV Camera Feed"
          className="video-feed-img"
          onError={(e) => {
            // Placeholder if camera is offline or restarting
            e.target.style.display = 'none';
          }}
        />
        <div className="feed-overlay-badge">
          <Eye size={13} />
          <span>{gestures_enabled ? 'TRACKING HAND' : 'STANDBY'}</span>
        </div>
      </div>

      {/* Live Gesture Feedback Box */}
      <div className="gesture-status-box">
        <div className="gesture-label-row">
          <h3>{gesture_label || 'Awaiting Gesture'}</h3>
          <span className="gesture-active-badge">
            {gesture_progress > 0 ? `${Math.round(gesture_progress * 100)}%` : (gestures_enabled ? 'READY' : 'OFF')}
          </span>
        </div>

        {/* Dynamic Hold Progress Bar */}
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${Math.min(100, Math.max(0, gesture_progress * 100))}%` }}
          />
        </div>
      </div>

      {/* Gesture Quick Guide Cards */}
      <div className="gesture-hints">
        <div className="hint-card">
          <div className="hint-icon-box">
            <ArrowLeftRight size={16} />
          </div>
          <div className="hint-info">
            <h5>Point Right / Left</h5>
            <p>Next or previous song</p>
          </div>
        </div>

        <div className="hint-card">
          <div className="hint-icon-box">
            <Volume2 size={16} />
          </div>
          <div className="hint-info">
            <h5>Two Fingers / One</h5>
            <p>Hold for volume up / down</p>
          </div>
        </div>

        <div className="hint-card">
          <div className="hint-icon-box">
            <Hand size={16} />
          </div>
          <div className="hint-info">
            <h5>Open Palm / Thumbs-Up</h5>
            <p>Hold to pause or play</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
