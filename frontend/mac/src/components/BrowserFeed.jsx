import { useState, useEffect } from 'react';

/**
 * Live screenshot feed. Preloads each new blob URL before swapping <img> src so rapid
 * WS frames don’t reset opacity / flash blank (previous: opacity 0 until onLoad per URL).
 */
export default function BrowserFeed({ screenshotUrl, size = 'thumbnail' }) {
  const [displayUrl, setDisplayUrl] = useState(null);
  const isFull = size === 'full';
  const containerClass = `bf-container ${isFull ? 'bf-full' : 'bf-thumb'}`;

  useEffect(() => {
    let cancelled = false;
    if (!screenshotUrl) {
      setDisplayUrl(null);
      return undefined;
    }
    const img = new Image();
    img.onload = () => {
      if (!cancelled) setDisplayUrl(screenshotUrl);
    };
    img.onerror = () => {
      if (!cancelled) setDisplayUrl(screenshotUrl);
    };
    img.src = screenshotUrl;
    return () => {
      cancelled = true;
    };
  }, [screenshotUrl]);

  if (!screenshotUrl) {
    return (
      <div className={containerClass}>
        <div className="bf-placeholder">
          <div className="bf-pulse" />
        </div>
      </div>
    );
  }

  if (!displayUrl) {
    return (
      <div className={containerClass}>
        <div className="bf-placeholder">
          <div className="bf-pulse" />
        </div>
      </div>
    );
  }

  return (
    <div className={containerClass}>
      <img
        src={displayUrl}
        alt="Agent browser view"
        className="bf-img bf-img-visible"
        draggable={false}
      />
    </div>
  );
}
