import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Upload, Video, Smartphone } from 'lucide-react';

function PhoneQR() {
  const [detectedIP, setDetectedIP] = useState('');

  useEffect(() => {
    fetch('/api/local-ip')
      .then((r) => r.json())
      .then((d) => { if (d.ip) setDetectedIP(d.ip); })
      .catch(() => {});
  }, []);

  const phoneUrl = useMemo(() => {
    const host = detectedIP || window.location.hostname || 'localhost';
    const port = window.location.port || '8080';
    return `http://${host}:${port}/phone/`;
  }, [detectedIP]);
  const qrSrc = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&margin=8&data=${encodeURIComponent(phoneUrl)}&bgcolor=FFFFFF&color=4A0F18`;

  return (
    <div className="intake-qr-panel">
      <div className="intake-qr-badge">
        <Smartphone size={14} />
        <span>Capture from phone</span>
      </div>
      <div className="intake-qr-frame">
        <img src={qrSrc} alt="Phone QR" className="intake-qr-img" />
      </div>
      <div className="intake-qr-url">{phoneUrl}</div>
    </div>
  );
}

export default function IntakePanel({ job, items, onUpload, fullscreen }) {
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef(null);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const file = e.dataTransfer?.files?.[0];
    if (file?.type.startsWith('video/')) {
      const url = URL.createObjectURL(file);
      onUpload(file, url);
    }
  }, [onUpload]);

  const handleFileSelect = useCallback((e) => {
    const file = e.target.files?.[0];
    if (file) {
      const url = URL.createObjectURL(file);
      onUpload(file, url);
    }
  }, [onUpload]);

  if (!fullscreen) return null;

  return (
    <div className="intake-fs">
      <motion.div
        className="intake-fs-content"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <div className="intake-fs-header">
          <h1 className="intake-fs-title">Film it. Sell it.</h1>
          <p className="intake-fs-subtitle">
            One video. Every marketplace. Zero effort.
          </p>
        </div>

        <div className="intake-cards-row">
          <div
            className={`intake-drop-card ${dragActive ? 'active' : ''}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
          >
            <div className="intake-drop-icon-ring">
              <Video size={28} />
            </div>
            <span className="intake-drop-label">Drop video or click to browse</span>
            <span className="intake-drop-hint">MP4, MOV up to 500MB</span>
            <div className="intake-drop-cta">
              <Upload size={14} />
              <span>Choose file</span>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept="video/*"
              className="upload-input"
              onChange={handleFileSelect}
            />
          </div>

          <div className="intake-divider">
            <span className="intake-divider-text">or</span>
          </div>

          <PhoneQR />
        </div>
      </motion.div>
    </div>
  );
}
