import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Video, Package, AlertTriangle, CheckCircle, ChevronLeft, ChevronRight } from 'lucide-react';
import Badge from '../shared/Badge';

function getConditionLabel(item) {
  const visible = item.visible_defects || [];
  const spoken = item.spoken_defects || [];
  if (visible.length + spoken.length === 0) return 'Like New';
  if (visible.some((d) => d.severity === 'major')) return 'Fair';
  return 'Good';
}

function getDefectStrings(item) {
  const visible = (item.visible_defects || []).map((d) => d.description);
  const spoken = item.spoken_defects || [];
  return [...visible, ...spoken];
}

function FrameGallery({ frames, name }) {
  const [activeIdx, setActiveIdx] = useState(0);
  if (!frames || frames.length === 0) {
    return (
      <div className="cf-gallery-empty">
        <Package size={28} />
      </div>
    );
  }

  return (
    <div className="cf-gallery">
      <div className="cf-gallery-main">
        <img src={frames[activeIdx]} alt={name} />
        {frames.length > 1 && (
          <>
            <button className="cf-gallery-nav cf-gallery-prev" onClick={() => setActiveIdx((i) => (i - 1 + frames.length) % frames.length)}>
              <ChevronLeft size={14} />
            </button>
            <button className="cf-gallery-nav cf-gallery-next" onClick={() => setActiveIdx((i) => (i + 1) % frames.length)}>
              <ChevronRight size={14} />
            </button>
          </>
        )}
        <div className="cf-gallery-counter">{activeIdx + 1}/{frames.length}</div>
      </div>
      {frames.length > 1 && (
        <div className="cf-gallery-strip">
          {frames.map((f, i) => (
            <button
              key={i}
              className={`cf-gallery-dot ${i === activeIdx ? 'active' : ''}`}
              onClick={() => setActiveIdx(i)}
            >
              <img src={f} alt="" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ConditionFusion({ items, job }) {
  const videoUrl = job?.video_url;

  return (
    <div className="condition-fusion">
      <div className="cf-video-section">
        {videoUrl ? (
          <video
            src={videoUrl}
            className="cf-video-player"
            controls
            muted
            playsInline
          />
        ) : (
          <div className="cf-video-placeholder">
            <Video size={40} />
          </div>
        )}
      </div>

      <div className="cf-items-section">
        <AnimatePresence>
          {items.map((item, index) => {
            const condition = getConditionLabel(item);
            const defects = getDefectStrings(item);
            return (
              <motion.div
                key={item.item_id}
                className="cf-item-card"
                initial={{ opacity: 0, x: 40 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{
                  delay: index * 0.15,
                  type: 'spring',
                  stiffness: 200,
                  damping: 20,
                }}
              >
                <FrameGallery frames={item.hero_frame_paths} name={item.name_guess} />
                <div className="cf-item-details">
                  <div className="cf-item-name">{item.name_guess}</div>
                  {defects.length > 0 && (
                    <div className="cf-item-defects">
                      <AlertTriangle size={11} style={{ display: 'inline', marginRight: 4 }} />
                      {defects.join(' · ')}
                    </div>
                  )}
                  {item.accessories_included?.length > 0 && (
                    <div className="cf-item-accessories">
                      <CheckCircle size={11} style={{ display: 'inline', marginRight: 4 }} />
                      {item.accessories_included.join(' · ')}
                    </div>
                  )}
                  <div className="cf-item-tags">
                    <Badge variant={condition === 'Like New' ? 'success' : 'warning'}>
                      {condition}
                    </Badge>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
