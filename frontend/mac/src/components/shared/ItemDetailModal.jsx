import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, useMotionValue } from 'framer-motion';
import { ChevronLeft, ChevronRight } from 'lucide-react';

function ItemCarousel({ frames, alt }) {
  const [idx, setIdx] = useState(0);
  const count = frames.length;
  const dragX = useMotionValue(0);

  const prev = () => setIdx((i) => Math.max(0, i - 1));
  const next = () => setIdx((i) => Math.min(count - 1, i + 1));

  const onDragEnd = () => {
    const x = dragX.get();
    if (x <= -30 && idx < count - 1) next();
    else if (x >= 30 && idx > 0) prev();
  };

  if (count === 0) return null;
  if (count === 1) {
    return (
      <div className="icr-single">
        <img src={frames[0]} alt={alt} />
      </div>
    );
  }

  return (
    <div className="icr-wrap">
      <div className="icr-viewport">
        <motion.div
          className="icr-track"
          drag="x"
          dragConstraints={{ left: 0, right: 0 }}
          dragMomentum={false}
          style={{ x: dragX }}
          animate={{ translateX: `${-idx * 100}%` }}
          onDragEnd={onDragEnd}
          transition={{ type: 'spring', damping: 26, stiffness: 180, mass: 0.8 }}
        >
          {frames.map((src, i) => (
            <div key={i} className="icr-slide">
              <img src={src} alt={`${alt} — frame ${i + 1}`} />
            </div>
          ))}
        </motion.div>
      </div>

      <motion.button className="icr-nav icr-nav-prev" disabled={idx === 0} onClick={prev}
        whileHover={{ scale: 1.15, backgroundColor: 'var(--bg-card)' }} whileTap={{ scale: 0.9 }}>
        <ChevronLeft size={16} />
      </motion.button>
      <motion.button className="icr-nav icr-nav-next" disabled={idx === count - 1} onClick={next}
        whileHover={{ scale: 1.15, backgroundColor: 'var(--bg-card)' }} whileTap={{ scale: 0.9 }}>
        <ChevronRight size={16} />
      </motion.button>

      <div className="icr-dots">
        {frames.map((_, i) => (
          <motion.button key={i} className={`icr-dot${i === idx ? ' icr-dot-active' : ''}`}
            onClick={() => setIdx(i)} whileHover={{ scale: 1.4 }} whileTap={{ scale: 0.8 }}
            animate={i === idx ? { scale: 1.3, opacity: 1 } : { scale: 1, opacity: 0.4 }}
            transition={{ type: 'spring', damping: 15, stiffness: 400 }} />
        ))}
      </div>
    </div>
  );
}

export default function ItemDetailModal({ item, onClose }) {
  if (!item) return null;

  const frames = item.hero_frame_paths || [];
  const condition = item.visible_defects?.length || item.spoken_defects?.length
    ? (item.visible_defects?.some?.((d) => d.severity === 'major') ? 'Fair' : 'Good')
    : 'Like New';

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  const E = [0.32, 0.72, 0, 1];

  const allDefects = [
    ...(item.visible_defects || []).map((d) => ({ label: 'Defect', text: d.description || d })),
    ...(item.spoken_defects || []).map((d) => ({ label: 'Seller Note', text: typeof d === 'string' ? d : d.description })),
  ];

  const leftBubbles = [
    { label: 'Condition', value: condition },
    ...allDefects.map((d) => ({ label: d.label, value: d.text })),
  ].filter(Boolean);

  const rightBubbles = [
    { label: 'Item Type', value: item.name_guess?.split(' ').slice(0, 2).join(' ') || 'Unknown' },
    frames.length > 1 && { label: 'Views', value: `${frames.length} angles captured` },
  ].filter(Boolean);

  const smooth = { type: 'spring', damping: 30, stiffness: 170, mass: 1 };
  const gentle = { type: 'spring', damping: 35, stiffness: 150, mass: 1.2 };

  return createPortal(
    <motion.div
      className="ide-overlay"
      key="item-detail-modal"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
      onClick={onClose}
    >
      <motion.button className="ide-close"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        transition={{ delay: 0.4, duration: 0.3 }} onClick={onClose}>
        ×
      </motion.button>

      <div className="ide-canvas" onClick={(e) => e.stopPropagation()}>
        <motion.div className="ide-hero"
          initial={{ scale: 0.85, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.9, opacity: 0, y: 10, transition: { duration: 0.3, ease: [0.4, 0, 1, 1] } }}
          transition={{ ...smooth, delay: 0.08 }}>
          <div className="ide-hero-glow" />
          <div className="ide-hero-img-wrap">
            {frames.length > 0 ? (
              <ItemCarousel frames={frames} alt={item.name_guess} />
            ) : (
              <div className="ide-hero-placeholder" />
            )}
          </div>
          <h2 className="ide-hero-name">{item.name_guess}</h2>
        </motion.div>

        <div className="ide-bubbles ide-bubbles-left">
          {leftBubbles.map((b, i) => (
            <motion.div key={`l-${i}`} className="ide-bubble"
              style={{ '--float-dur': `${5 + i * 1.1}s`, '--float-delay': `${i * 0.5}s`, '--float-y': `${-4 - i * 1.5}px` }}
              initial={{ opacity: 0, x: 100, scale: 0.6 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 60, scale: 0.7, transition: { duration: 0.25, delay: i * 0.04, ease: [0.4, 0, 1, 1] } }}
              transition={{ delay: 0.2 + i * 0.09, ...gentle }}>
              <div className="ide-bubble-label">{b.label}</div>
              <div className="ide-bubble-value">{b.value}</div>
            </motion.div>
          ))}
        </div>

        <div className="ide-bubbles ide-bubbles-right">
          {rightBubbles.map((b, i) => (
            <motion.div key={`r-${i}`} className="ide-bubble"
              style={{ '--float-dur': `${5.5 + i * 1}s`, '--float-delay': `${0.3 + i * 0.6}s`, '--float-y': `${-5 - i * 1.5}px` }}
              initial={{ opacity: 0, x: -100, scale: 0.6 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: -60, scale: 0.7, transition: { duration: 0.25, delay: i * 0.04, ease: [0.4, 0, 1, 1] } }}
              transition={{ delay: 0.2 + i * 0.09, ...gentle }}>
              <div className="ide-bubble-label">{b.label}</div>
              <div className="ide-bubble-value">{b.value}</div>
            </motion.div>
          ))}
        </div>

        <div className="ide-bottom" />
      </div>
    </motion.div>,
    document.body
  );
}
