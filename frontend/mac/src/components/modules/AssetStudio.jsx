import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { Image, Sparkles, AlertTriangle, Camera } from 'lucide-react';

const DEMO_FRAMES = [
  { id: 'raw', label: 'Raw Frame', icon: Camera },
  { id: 'optimized', label: 'Optimized', icon: Sparkles },
  { id: 'defect', label: 'Defect Proof', icon: AlertTriangle },
];

export default function AssetStudio({ items, listings }) {
  const [sliderValue, setSliderValue] = useState(50);

  const imageFrames = useMemo(() => {
    const allListings = Object.values(listings || {});
    const images = allListings.flatMap((l) => l.images || []);
    if (images.length === 0) return null;

    const hero = images.find((i) => i.role === 'hero');
    const defects = images.filter((i) => i.role === 'defect_proof');
    const optimized = images.find((i) => i.optimized);

    return { hero, defects, optimized, all: images };
  }, [listings]);

  return (
    <div className="asset-studio">
      {imageFrames ? (
        <>
          {imageFrames.hero && (
            <motion.div
              className="as-frame"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0 }}
            >
              <div className="as-frame-header">
                <Camera size={12} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />
                Hero Image
              </div>
              <div className="as-frame-image">
                <img
                  src={imageFrames.hero.path}
                  alt="Hero"
                  style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'inherit' }}
                />
              </div>
            </motion.div>
          )}
          {imageFrames.optimized && (
            <motion.div
              className="as-frame"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.12 }}
            >
              <div className="as-frame-header">
                <Sparkles size={12} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />
                Optimized
              </div>
              <div className="as-frame-image">
                <img
                  src={imageFrames.optimized.path}
                  alt="Optimized"
                  style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'inherit' }}
                />
                <motion.div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'linear-gradient(135deg, rgba(99,102,241,0.08), transparent)',
                  }}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.5 }}
                />
              </div>
            </motion.div>
          )}
          {imageFrames.defects.length > 0 && (
            <motion.div
              className="as-frame"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.24 }}
            >
              <div className="as-frame-header">
                <AlertTriangle size={12} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />
                Defect Proof ({imageFrames.defects.length})
              </div>
              <div className="as-frame-image">
                <img
                  src={imageFrames.defects[0].path}
                  alt="Defect proof"
                  style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'inherit' }}
                />
                <motion.div
                  style={{
                    position: 'absolute',
                    top: '20%',
                    left: '30%',
                    width: 60,
                    height: 60,
                    border: '2px solid var(--danger)',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--danger-dim)',
                  }}
                  initial={{ opacity: 0, scale: 0 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.7, type: 'spring' }}
                />
              </div>
            </motion.div>
          )}
        </>
      ) : (
        DEMO_FRAMES.map((frame, index) => (
          <motion.div
            key={frame.id}
            className="as-frame"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.12 }}
          >
            <div className="as-frame-header">
              <frame.icon
                size={12}
                style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }}
              />
              {frame.label}
            </div>
            <div className="as-frame-image">
              <Image size={36} />
              {frame.id === 'optimized' && (
                <motion.div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'linear-gradient(135deg, rgba(99,102,241,0.08), transparent)',
                  }}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.5 }}
                />
              )}
              {frame.id === 'defect' && (
                <motion.div
                  style={{
                    position: 'absolute',
                    top: '20%',
                    left: '30%',
                    width: 60,
                    height: 60,
                    border: '2px solid var(--danger)',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--danger-dim)',
                  }}
                  initial={{ opacity: 0, scale: 0 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.7, type: 'spring' }}
                />
              )}
            </div>
          </motion.div>
        ))
      )}

      <div style={{ gridColumn: '1 / -1' }}>
        <div className="as-slider">
          <span className="as-slider-label">Raw</span>
          <div
            className="as-slider-track"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              setSliderValue(Math.round(((e.clientX - rect.left) / rect.width) * 100));
            }}
          >
            <div className="as-slider-fill" style={{ width: `${sliderValue}%` }} />
          </div>
          <span className="as-slider-label">Enhanced</span>
        </div>
      </div>
    </div>
  );
}
