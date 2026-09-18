import React from 'react';
import { Waves, Sparkles, Radio, CheckCircle2, ShieldAlert } from 'lucide-react';

export function Navbar({ state, wsConnected, onAction }) {
  const { gestures_enabled, demo, connected } = state;

  return (
    <header className="navbar">
      <div className="brand">
        <div className="brand-logo-wrapper">
          <img src="/favicon.svg" alt="Handsfree Logo" className="brand-logo-img" />
        </div>
        <div className="brand-text">
          <h1>Handsfree</h1>
          <p>Touchless Music Experience</p>
        </div>
      </div>

      <div className="nav-actions">
        {/* Connection health */}
        <div className={`badge ${wsConnected ? 'badge-active' : ''}`}>
          <span className={`status-dot ${wsConnected ? 'active' : ''}`} />
          {wsConnected ? 'Vision Engine Active' : 'Connecting...'}
        </div>

        {/* Gestures toggle */}
        <button
          className={`btn-pill ${gestures_enabled ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => onAction('toggle_gestures')}
        >
          <Radio size={16} />
          {gestures_enabled ? 'Gestures Active' : 'Gestures Off'}
        </button>

        {/* Mode / Spotify status */}
        <button
          className="btn-pill btn-secondary"
          onClick={() => onAction('connect')}
        >
          {demo ? (
            <>
              <Sparkles size={16} />
              <span>Demo Mode</span>
            </>
          ) : connected ? (
            <>
              <CheckCircle2 size={16} color="#1ed760" />
              <span>Spotify Connected</span>
            </>
          ) : (
            <>
              <ShieldAlert size={16} />
              <span>Connect Spotify</span>
            </>
          )}
        </button>
      </div>
    </header>
  );
}
