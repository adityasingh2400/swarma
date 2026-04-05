import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, Smartphone, ArrowUpFromLine, Scan } from 'lucide-react';

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
      className="intake-qr-panel glass-enhanced"
      initial={{ opacity: 0, y: 40, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 1.0, delay: 3.6, ease: [0.16, 1, 0.3, 1] }}
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
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef(null);
  const pendingRef = useRef(null);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!uploading) setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  }, [uploading]);

  const startUpload = useCallback((file) => {
    const url = URL.createObjectURL(file);
    pendingRef.current = { file, url };
    setDragActive(false);
    setUploading(true);
    setTimeout(() => {
      if (pendingRef.current) onUpload(pendingRef.current.file, pendingRef.current.url);
    }, 300);
  }, [onUpload]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (uploading) return;
    const file = e.dataTransfer?.files?.[0];
    if (file?.type.startsWith('video/')) startUpload(file);
  }, [uploading, startUpload]);

  const handleFileSelect = useCallback((e) => {
    const file = e.target.files?.[0];
    if (file && !uploading) startUpload(file);
  }, [uploading, startUpload]);

  if (!fullscreen) return null;

  return (
    <div className="intake-fs">
      <div className="intake-fs-content">
        <motion.div
          className="intake-fs-header"
          animate={uploading ? { opacity: 0, y: -12 } : {}}
          transition={uploading ? { duration: 0.4, ease: EASE } : {}}
        >
          <h1 className="intake-fs-title">
            {'Film it.'.split('').map((ch, i) => (
              <motion.span
                key={`a${i}`}
                className="intake-char"
                initial={{ opacity: 0, y: 40, filter: 'blur(8px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                transition={{ duration: 0.9, delay: 0.4 + i * 0.07, ease: [0.16, 1, 0.3, 1] }}
              >
                {ch === ' ' ? '\u00A0' : ch}
              </motion.span>
            ))}
            <motion.span
              className="intake-char-space"
              initial={{ width: 0 }}
              animate={{ width: '0.35em' }}
              transition={{ duration: 0.6, delay: 1.1, ease: [0.16, 1, 0.3, 1] }}
            />
            {'Sell it.'.split('').map((ch, i) => (
              <motion.span
                key={`b${i}`}
                className="intake-char"
                initial={{ opacity: 0, y: 40, filter: 'blur(8px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                transition={{ duration: 0.9, delay: 1.3 + i * 0.07, ease: [0.16, 1, 0.3, 1] }}
              >
                {ch === ' ' ? '\u00A0' : ch}
              </motion.span>
            ))}
          </h1>

          <motion.p
            className="intake-fs-subtitle"
            initial={{ opacity: 0, y: 16, filter: 'blur(6px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            transition={{ duration: 1.0, delay: 2.4, ease: [0.16, 1, 0.3, 1] }}
          >
            One video. Every marketplace. Zero effort.
          </motion.p>
        </motion.div>

        <motion.div
          className="intake-cards-row"
          animate={uploading ? { opacity: 0, scale: 0.95, y: 10 } : {}}
          transition={uploading ? { duration: 0.5, ease: EASE } : {}}
        >
          <motion.div
            className={`intake-drop-card glass-enhanced ${dragActive ? 'active' : ''} ${uploading ? 'uploading' : ''}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => !uploading && inputRef.current?.click()}
            initial={{ opacity: 0, y: 40, scale: 0.94 }}
            animate={uploading
              ? { scale: 0.92, opacity: 0.7 }
              : { opacity: 1, y: 0, scale: 1 }
            }
            transition={uploading
              ? { duration: 0.4, ease: EASE }
              : { duration: 1.0, delay: 3.0, ease: [0.16, 1, 0.3, 1] }
            }
            whileHover={uploading ? {} : { y: -2, transition: { duration: 0.25, ease: EASE } }}
          >
            <AnimatePresence mode="wait">
              {uploading && pendingRef.current ? (
                <motion.div
                  key="uploading-state"
                  className="intake-drop-uploading"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.35, ease: EASE }}
                >
                  <motion.div
                    className="intake-video-preview"
                    layoutId="video-player"
                    transition={{ type: 'spring', damping: 30, stiffness: 180, mass: 1 }}
                  >
                    <video src={pendingRef.current.url} muted autoPlay loop playsInline />
                    <div className="mp-scanbar" />
                    <div className="intake-preview-badge">
                      <Scan size={10} />
                      <span>SCANNING</span>
                    </div>
                  </motion.div>
                </motion.div>
              ) : (
                <motion.div
                  key="idle-state"
                  className="intake-drop-idle"
                  exit={{ opacity: 0, scale: 0.95, transition: { duration: 0.25 } }}
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
                </motion.div>
              )}
            </AnimatePresence>

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
            animate={uploading ? { opacity: 0 } : { opacity: 1 }}
            transition={{ duration: uploading ? 0.25 : 0.8, delay: uploading ? 0 : 3.4, ease: [0.16, 1, 0.3, 1] }}
          >
            <span className="intake-divider-text">or</span>
          </motion.div>

          <motion.div
            animate={uploading ? { opacity: 0, scale: 0.95 } : {}}
            transition={uploading ? { duration: 0.3, ease: EASE } : {}}
          >
            <PhoneQR />
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}
