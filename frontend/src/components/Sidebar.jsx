import React from 'react';
import { Library, ListMusic, RotateCw } from 'lucide-react';

export function Sidebar({ state, onAction }) {
  const { playlists = [], selected_playlist } = state;

  return (
    <aside className="panel">
      <div className="panel-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Library size={18} color="var(--spotify-green)" />
          <span className="panel-title">Your Library</span>
        </div>
        <button
          className="control-btn"
          title="Refresh playlists"
          onClick={() => onAction('library', 0)}
        >
          <RotateCw size={15} />
        </button>
      </div>

      <div className="panel-scroll">
        {playlists.map((playlist) => {
          const isActive = selected_playlist?.id === playlist.id;
          return (
            <div
              key={playlist.id}
              className={`playlist-item ${isActive ? 'active' : ''}`}
              onClick={() => onAction('playlist', playlist)}
            >
              <div className="playlist-icon">
                <ListMusic size={20} />
              </div>
              <div className="playlist-info">
                <h4>{playlist.name}</h4>
                <p>{playlist.owner?.display_name || 'Playlist'}</p>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
