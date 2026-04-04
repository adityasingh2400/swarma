import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Rocket, ExternalLink, CheckCircle, Loader2 } from 'lucide-react';
import Badge from '../shared/Badge';

const STAGES = ['preparing', 'drafting', 'publishing', 'live'];

const DEMO_PLATFORMS = [
  { id: 'l1', platform: 'ebay', status: 'live', link: '#' },
  { id: 'l2', platform: 'mercari', status: 'publishing', link: null },
  { id: 'l3', platform: 'facebook', status: 'drafting', link: null },
  { id: 'l4', platform: 'offerup', status: 'preparing', link: null },
  { id: 'l5', platform: 'poshmark', status: 'preparing', link: null },
];

function StatusPill({ status }) {
  const stageIndex = STAGES.indexOf(status);

  return (
    <div className="mp-status">
      {STAGES.map((stage, i) => (
        <motion.span
          key={stage}
          className={`mp-status-pill ${i <= stageIndex ? status : ''}`}
          initial={false}
          animate={{
            opacity: i <= stageIndex ? 1 : 0.3,
            scale: i === stageIndex ? 1.05 : 1,
          }}
          transition={{ duration: 0.3 }}
        >
          {i === stageIndex && stage === 'live' && (
            <CheckCircle size={10} style={{ display: 'inline', marginRight: 3 }} />
          )}
          {i === stageIndex && stage === 'publishing' && (
            <Loader2 size={10} style={{ display: 'inline', marginRight: 3, animation: 'spin 1s linear infinite' }} />
          )}
          {stage}
        </motion.span>
      ))}
    </div>
  );
}

export default function MultiPostEngine({ items, listings, onExecuteItem }) {
  const [launched, setLaunched] = useState(false);
  const [simPlatforms, setSimPlatforms] = useState(DEMO_PLATFORMS);

  const realPlatforms = useMemo(() => {
    const allListings = Object.values(listings || {});
    return allListings.flatMap((l) =>
      (l.platform_listings || []).map((pl, i) => ({
        id: `${l.item_id}-${pl.platform}-${i}`,
        platform: pl.platform,
        status: pl.status || 'preparing',
        link: pl.url || null,
        error: pl.error || null,
      }))
    );
  }, [listings]);

  const platforms = realPlatforms.length > 0 ? realPlatforms : simPlatforms;

  useEffect(() => {
    if (!launched || realPlatforms.length > 0) return;
    let step = 0;
    const interval = setInterval(() => {
      step++;
      setSimPlatforms((prev) =>
        prev.map((p, i) => {
          const targetStage = Math.min(STAGES.length - 1, step - i);
          return targetStage >= 0
            ? { ...p, status: STAGES[targetStage], link: targetStage === 3 ? '#' : null }
            : p;
        })
      );
      if (step >= STAGES.length + platforms.length) clearInterval(interval);
    }, 1200);
    return () => clearInterval(interval);
  }, [launched, realPlatforms.length]);

  const handleLaunch = () => {
    setLaunched(true);
    const firstItem = items?.[0];
    const platformNames = platforms.map((p) => p.platform);
    onExecuteItem?.(firstItem?.item_id, platformNames);
  };

  return (
    <div className="multipost-engine">
      {platforms.map((plat, index) => (
        <motion.div
          key={plat.id}
          className="mp-row"
          initial={{ opacity: 0, x: -16 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.08 }}
        >
          <div className="mp-platform">
            <Badge platform={plat.platform} />
          </div>
          <StatusPill status={plat.status} />
          {plat.error && (
            <span style={{ color: 'var(--danger)', fontSize: 11 }}>{plat.error}</span>
          )}
          {plat.link && (
            <a href={plat.link} target="_blank" rel="noopener noreferrer" className="mp-link">
              <ExternalLink size={14} />
            </a>
          )}
        </motion.div>
      ))}

      <motion.button
        className="mp-launch-btn"
        onClick={handleLaunch}
        disabled={launched}
        whileHover={{ scale: launched ? 1 : 1.02 }}
        whileTap={{ scale: launched ? 1 : 0.98 }}
      >
        <Rocket size={18} />
        {launched ? 'Launch Sequence Active' : 'Launch All Platforms'}
      </motion.button>
    </div>
  );
}
