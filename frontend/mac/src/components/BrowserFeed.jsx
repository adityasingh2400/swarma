import { useState, useEffect } from 'react';

export default function BrowserFeed({ screenshotUrl, size = 'thumbnail' }) {
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
  }, [screenshotUrl]);

  const isFull = size === 'full';
  const containerClass = `bf-container ${isFull ? 'bf-full' : 'bf-thumb'}`;

  if (!screenshotUrl) {
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
        src={screenshotUrl}
        alt="Agent browser view"
        className={`bf-img ${loaded ? 'bf-img-visible' : ''}`}
        onLoad={() => setLoaded(true)}
        draggable={false}
      />
    </div>
  );
}
