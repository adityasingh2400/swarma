import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, Video, Smartphone, ArrowUpFromLine, QrCode } from 'lucide-react';

const EASE = [0.32, 0.72, 0, 1];

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
  const qrSrc = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&margin=8&data=${encodeURIComponent(phoneUrl)}&bgcolor=FFF7F0&color=EF4444`;

  return (
    <motion.div
      className="intake-qr-panel"
      initial={{ opacity: 0, y: 30, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.7, delay: 2.1, ease: EASE }}
    >
      <div className="intake-qr-badge">
        <Smartphone size={14} />
        <span>Capture from phone</span>
      </div>
      <div className="intake-qr-frame">
        <img src={qrSrc} alt="Phone QR" className="intake-qr-img" />
      </div>
      <div className="intake-qr-url">{phoneUrl}</div>
    </motion.div>
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
      <div className="intake-fs-content">
        <div className="intake-fs-header">
          <h1 className="intake-fs-title">
            {'Film it.'.split('').map((ch, i) => (
              <motion.span
                key={`a${i}`}
                className="intake-char"
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.1 + i * 0.04, ease: EASE }}
              >
                {ch === ' ' ? '\u00A0' : ch}
              </motion.span>
            ))}
            <motion.span
              className="intake-char-space"
              initial={{ width: 0 }}
              animate={{ width: '0.3em' }}
              transition={{ duration: 0.3, delay: 0.4, ease: EASE }}
            />
            {'Sell it.'.split('').map((ch, i) => (
              <motion.span
                key={`b${i}`}
                className="intake-char"
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.5 + i * 0.04, ease: EASE }}
              >
                {ch === ' ' ? '\u00A0' : ch}
              </motion.span>
            ))}
          </h1>

          <motion.p
            className="intake-fs-subtitle"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 1.0, ease: EASE }}
          >
            One video. Every marketplace. Zero effort.
          </motion.p>
        </div>

        <div className="intake-cards-row">
          <motion.div
            className={`intake-drop-card ${dragActive ? 'active' : ''}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            initial={{ opacity: 0, y: 30, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.7, delay: 1.8, ease: EASE }}
            whileHover={{ y: -2, transition: { duration: 0.25, ease: EASE } }}
          >
            <div className="intake-drop-visual">
              <motion.div
                className="intake-drop-icon-ring"
                animate={dragActive ? { scale: 1.1 } : { scale: 1 }}
                transition={{ duration: 0.3, ease: EASE }}
              >
                <ArrowUpFromLine size={24} strokeWidth={2} />
              </motion.div>
              <div className="intake-drop-ring-pulse" />
            </div>

            <div className="intake-drop-text">
              <span className="intake-drop-label">
                {dragActive ? 'Drop to upload' : 'Drop your video here'}
              </span>
              <span className="intake-drop-hint">or click anywhere to browse files</span>
            </div>

            <div className="intake-drop-footer">
              <div className="intake-drop-cta">
                <Upload size={14} strokeWidth={2.5} />
                <span>Choose file</span>
              </div>
              <span className="intake-drop-formats">MP4, MOV &middot; up to 500MB</span>
            </div>

            <input
              ref={inputRef}
              type="file"
              accept="video/*"
              className="upload-input"
              onChange={handleFileSelect}
            />
          </motion.div>

          <motion.div
            className="intake-divider"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 2.0, ease: EASE }}
          >
            <span className="intake-divider-text">or</span>
          </motion.div>

          <PhoneQR />
        </div>
      </div>
    </div>
  );
}
