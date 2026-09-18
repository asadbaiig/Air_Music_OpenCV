import React from 'react';
import { Music, Play, Disc } from 'lucide-react';

function formatDuration(ms) {
  const totalSec = Math.max(0, Math.floor((ms || 0) / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${sec < 10 ? '0' : ''}${sec}`;
}

export function TrackList({ state, onAction }) {
  const { tracks = [], selected_playlist, playback } = state;
  const currentUri = playback?.item?.uri;
  const isPlaying = playback?.is_playing;

  return (
    <main className="panel">
      {/* Banner */}
      <div className="tracklist-header-banner">
        <div className="playlist-banner-art">
          <Disc size={48} strokeWidth={1.5} />
        </div>
        <div className="banner-meta">
          <h2>{selected_playlist?.name || 'All Tracks'}</h2>
          <p>
            {tracks.length} songs • {selected_playlist?.owner?.display_name || 'Air Music Library'}
          </p>
        </div>
      </div>

      {/* Songs Table */}
      <div className="panel-scroll" style={{ padding: '0' }}>
        <table className="track-table">
          <thead>
            <tr>
              <th style={{ width: '48px', textAlign: 'center' }}>#</th>
              <th>Title</th>
              <th>Album</th>
              <th style={{ width: '80px', textAlign: 'right', paddingRight: '24px' }}>Time</th>
            </tr>
          </thead>
          <tbody>
            {tracks.map((row, index) => {
              const track = row.track || {};
              const isCurrent = track.uri && track.uri === currentUri;

              return (
                <tr
                  key={track.uri || index}
                  className={`track-row ${isCurrent ? 'active' : ''}`}
                  onClick={() => onAction('play_track', { position: index })}
                >
                  <td className="track-num" style={{ textAlign: 'center' }}>
                    {isCurrent && isPlaying ? (
                      <div className="eq-bars">
                        <div className="eq-bar" />
                        <div className="eq-bar" />
                        <div className="eq-bar" />
                        <div className="eq-bar" />
                      </div>
                    ) : (
                      <span>{index + 1}</span>
                    )}
                  </td>
                  <td>
                    <div className="track-title-cell">
                      <span className="track-name">{track.name || 'Untitled Song'}</span>
                      <span className="track-artists">
                        {(track.artists || []).map((a) => a.name).join(', ') || 'Unknown Artist'}
                      </span>
                    </div>
                  </td>
                  <td className="track-album">{track.album?.name || 'Single'}</td>
                  <td className="track-duration" style={{ paddingRight: '24px' }}>
                    {formatDuration(track.duration_ms)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
