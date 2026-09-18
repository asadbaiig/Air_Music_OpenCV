import React from 'react';
import { Sparkles } from 'lucide-react';

export function GestureToast({ gesture }) {
  if (!gesture) return null;

  return (
    <div className="gesture-toast">
      <div className="gesture-toast-icon">
        <Sparkles size={16} />
      </div>
      <span className="gesture-toast-text">{gesture}</span>
    </div>
  );
}
