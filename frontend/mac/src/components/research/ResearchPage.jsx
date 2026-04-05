import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import CircularCarousel from '../shared/CircularCarousel';
import {
  Search, TrendingUp, Wrench,
  CheckCircle2, AlertTriangle,
  Zap, Sparkles, Package,
  MessageSquare, Eye, Timer, ChevronRight,
  Megaphone, Users, MapPin, ArrowUpRight,
} from 'lucide-react';

const EASE = [0.32, 0.72, 0, 1];
const SPRING = { type: 'spring', damping: 25, stiffness: 200 };

const PLATFORM_META = {
  ebay:     { label: 'eBay',     color: '#FF6B6B', gradient: 'linear-gradient(135deg, #FF6B6B, #FF8E8E)' },
  mercari:  { label: 'Mercari',  color: '#A78BFA', gradient: 'linear-gradient(135deg, #A78BFA, #C4B5FD)' },
  facebook: { label: 'Facebook', color: '#FF9F43', gradient: 'linear-gradient(135deg, #FF9F43, #FFBE76)' },
};

// ── Animated price counter ───────────────────────────
function AnimatedPrice({ value, delay = 0 }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => {
      let start = 0;
      const end = value;
      const duration = 600;
      const startTime = performance.now();
      const tick = (now) => {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        setDisplay(Math.round(start + (end - start) * eased));
        if (progress < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, delay * 1000);
    return () => clearTimeout(t);
  }, [value, delay]);
  return <span>${display}</span>;
}

// ── Circular confidence ring ─────────────────────────
function ConfidenceRing({ value, color, size = 40 }) {
  const r = (size - 6) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - value);
  return (
    <div className="rp2-ring-wrap" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(0,0,0,0.06)" strokeWidth="3" />
        <motion.circle
          cx={size/2} cy={size/2} r={r}
          fill="none" stroke={color} strokeWidth="3" strokeLinecap="round"
          strokeDasharray={circ} strokeDashoffset={circ}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1, delay: 0.5, ease: EASE }}
          style={{ transformOrigin: 'center', transform: 'rotate(-90deg)' }}
        />
      </svg>
      <span className="rp2-ring-label">{Math.round(value * 100)}%</span>
    </div>
  );
}

// ── Floating ambient blobs (background decoration) ───
function AmbientBlobs({ colors }) {
  return (
    <div className="rp2-blobs" aria-hidden>
      {colors.map((c, i) => (
        <motion.div
          key={i}
          className="rp2-blob"
          style={{ background: c, left: `${20 + i * 25}%`, top: `${15 + (i % 2) * 50}%` }}
          animate={{
            x: [0, 15 * (i % 2 ? 1 : -1), 0],
            y: [0, 10 * (i % 2 ? -1 : 1), 0],
            scale: [1, 1.1, 1],
          }}
          transition={{ duration: 6 + i * 2, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}
    </div>
  );
}

// ── Platform result row ──────────────────────────────
function PlatResult({ platform, price, delay = 0, scanning = false }) {
  const meta = PLATFORM_META[platform] || PLATFORM_META.ebay;
  return (
    <motion.div
      className="rp2-plat"
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, delay, ease: EASE }}
    >
      <div className="rp2-plat-dot" style={{ background: meta.color }} />
      <span className="rp2-plat-name">{meta.label}</span>
      {scanning ? (
        <motion.span
          className="rp2-plat-scan"
          animate={{ opacity: [0.3, 0.8, 0.3] }}
          transition={{ duration: 1.2, repeat: Infinity }}
        >
          searching...
        </motion.span>
      ) : (
        <span className="rp2-plat-price">${price}</span>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════
// RESALE PANEL — The star, floating right
// ═══════════════════════════════════════════════════════
function ResalePanel({ bids, phase }) {
  const bid = bids?.find(b => b.route_type === 'sell_as_is');
  const listings = bid?.comparable_listings || [];
  const isScanning = phase === 'scanning';
  const isDone = phase === 'done';

  return (
    <motion.div
      className="rp2-panel rp2-panel-resale"
      initial={{ opacity: 0, x: 60, scale: 0.92 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      transition={{ ...SPRING, delay: 0.3 }}
    >
      <div className="rp2-panel-glow rp2-glow-resale" />
      <div className="rp2-panel-inner">
        <div className="rp2-panel-head">
          <div className="rp2-panel-icon rp2-icon-resale"><TrendingUp size={16} /></div>
          <h3>Resale Value</h3>
          {isScanning && (
            <motion.div className="rp2-status rp2-status-scan" animate={{ opacity: [1, 0.5, 1] }} transition={{ duration: 1.2, repeat: Infinity }}>
              <Search size={11} /> Scanning
            </motion.div>
          )}
          {isDone && <div className="rp2-status rp2-status-done"><CheckCircle2 size={11} /> Found</div>}
        </div>

        <div className="rp2-panel-content">
          {isScanning && ['ebay', 'mercari', 'facebook'].map((p, i) => (
            <PlatResult key={p} platform={p} scanning delay={i * 0.15} />
          ))}
          {isDone && (
            <>
              {listings.slice(0, 3).map((l, i) => (
                <PlatResult key={i} platform={l.platform?.toLowerCase()} price={l.price} delay={i * 0.1} />
              ))}
              <motion.div
                className="rp2-value-display"
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.4, ...SPRING }}
              >
                <div className="rp2-value-main">
                  <AnimatedPrice value={bid?.estimated_value || 0} delay={0.5} />
                </div>
                <ConfidenceRing value={bid?.confidence || 0} color="var(--color-coral)" />
              </motion.div>
            </>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════
// REPAIR PANEL — Floating top, conditional
// ═══════════════════════════════════════════════════════
function RepairPanel({ item, bids, phase }) {
  const repairBid = bids?.find(b => b.route_type === 'repair_then_sell');
  const resaleBid = bids?.find(b => b.route_type === 'sell_as_is');
  const hasDamage = item.visible_defects?.length > 0 || item.spoken_defects?.length > 0;
  const isEval = phase === 'evaluating';
  const isDone = phase === 'done';
  const isViable = repairBid?.viable && hasDamage;
  const profit = isViable ? (repairBid.estimated_value - (resaleBid?.estimated_value || 0)) : 0;

  return (
    <motion.div
      className={`rp2-panel rp2-panel-repair ${isDone && !isViable ? 'rp2-panel-faded' : ''}`}
      initial={{ opacity: 0, y: -40, scale: 0.92 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ ...SPRING, delay: 0.5 }}
    >
      <div className="rp2-panel-glow rp2-glow-repair" />
      <div className="rp2-panel-inner">
        <div className="rp2-panel-head">
          <div className="rp2-panel-icon rp2-icon-repair"><Wrench size={15} /></div>
          <h3>Repair Route</h3>
          {isEval && (
            <motion.div className="rp2-status rp2-status-scan" animate={{ opacity: [1, 0.5, 1] }} transition={{ duration: 1.2, repeat: Infinity }}>
              <Eye size={11} /> Analyzing
            </motion.div>
          )}
          {isDone && isViable && <div className="rp2-status rp2-status-warn"><Zap size={11} /> Viable</div>}
          {isDone && !isViable && <div className="rp2-status rp2-status-skip">Skipped</div>}
        </div>

        <div className="rp2-panel-content">
          {isEval && (
            <motion.div className="rp2-eval-row" animate={{ opacity: [0.5, 1, 0.5] }} transition={{ duration: 2, repeat: Infinity }}>
              <MessageSquare size={13} />
              <span>Scanning video transcript for damage mentions...</span>
            </motion.div>
          )}

          {isDone && !hasDamage && (
            <div className="rp2-skip-row">
              <CheckCircle2 size={13} />
              <span>No damage detected — route not needed</span>
            </div>
          )}

          {isDone && hasDamage && (
            <>
              <div className="rp2-damage-row">
                <AlertTriangle size={12} />
                {item.visible_defects.map((d, i) => <span key={i}>{d.description}</span>)}
              </div>
              {isViable && (
                <div className="rp2-repair-compare">
                  <div className="rp2-compare-item">
                    <span className="rp2-compare-label">As-is</span>
                    <span className="rp2-compare-val">${resaleBid?.estimated_value || 0}</span>
                  </div>
                  <ArrowUpRight size={14} className="rp2-compare-arrow" />
                  <div className="rp2-compare-item rp2-compare-highlight">
                    <span className="rp2-compare-label">Repaired</span>
                    <span className="rp2-compare-val">${repairBid.estimated_value}</span>
                  </div>
                  <div className={`rp2-profit-tag ${profit > 30 ? 'rp2-profit-good' : 'rp2-profit-meh'}`}>
                    +${profit}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════
// GARBAGE PANEL — Floating bottom-left, compact
// ═══════════════════════════════════════════════════════
function GarbagePanel({ bids, phase }) {
  const resaleBid = bids?.find(b => b.route_type === 'sell_as_is');
  const isLow = resaleBid && resaleBid.estimated_value < 30;
  const isDone = phase === 'done';
  const isEval = phase === 'evaluating';

  return (
    <motion.div
      className={`rp2-panel rp2-panel-garbage ${isDone && !isLow ? 'rp2-panel-faded' : ''}`}
      initial={{ opacity: 0, y: 40, scale: 0.92 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ ...SPRING, delay: 0.65 }}
    >
      <div className="rp2-panel-inner">
        <div className="rp2-panel-head">
          <div className="rp2-panel-icon rp2-icon-garbage"><Megaphone size={15} /></div>
          <h3>Yard Sale</h3>
          {isEval && (
            <motion.div className="rp2-status rp2-status-scan" animate={{ opacity: [1, 0.5, 1] }} transition={{ duration: 1.2, repeat: Infinity }}>
              <Timer size={11} /> Checking
            </motion.div>
          )}
          {isDone && !isLow && <div className="rp2-status rp2-status-skip">Not needed</div>}
        </div>
        {isDone && !isLow && (
          <p className="rp2-skip-text">Resale value ${resaleBid?.estimated_value} — direct sale preferred</p>
        )}
        {isDone && isLow && (
          <div className="rp2-garbage-tactics">
            <span><MapPin size={11} /> Porch pickup</span>
            <span><Users size={11} /> Local collectors</span>
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════
// ITEM CENTER — The hero hub with glow
// ═══════════════════════════════════════════════════════
function ItemCenter({ item, index, totalItems }) {
  const hasDamage = item.visible_defects?.length > 0;
  return (
    <motion.div
      className="rp2-item-center"
      initial={{ scale: 0.6, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ ...SPRING, delay: 0.1 }}
    >
      {/* Radial glow behind item */}
      <div className="rp2-item-glow" />

      {/* Pulsing orbit ring */}
      <motion.div
        className="rp2-orbit-ring"
        animate={{ rotate: 360 }}
        transition={{ duration: 20, repeat: Infinity, ease: 'linear' }}
      >
        <div className="rp2-orbit-dot rp2-odot-1" />
        <div className="rp2-orbit-dot rp2-odot-2" />
        <div className="rp2-orbit-dot rp2-odot-3" />
      </motion.div>

      <div className="rp2-item-img-wrap">
        {item.hero_frame_paths?.[0] ? (
          <img src={item.hero_frame_paths[0]} alt={item.name_guess} className="rp2-item-img" />
        ) : (
          <div className="rp2-item-placeholder"><Package size={32} /></div>
        )}
      </div>
      <h2 className="rp2-item-name">{item.name_guess}</h2>
      <div className="rp2-item-tags">
        <span className={`rp2-cond-tag ${hasDamage ? 'rp2-cond-warn' : 'rp2-cond-good'}`}>
          {hasDamage ? 'Minor wear' : 'Excellent'}
        </span>
        <span className="rp2-item-count">{index + 1} of {totalItems}</span>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════
// ITEM UNIVERSE — One item with orbiting routes
// ═══════════════════════════════════════════════════════
function ItemUniverse({ item, bids, decision, index, totalItems }) {
  const [resalePhase, setResalePhase] = useState('idle');
  const [repairPhase, setRepairPhase] = useState('idle');
  const [garbagePhase, setGarbagePhase] = useState('idle');
  const [showRec, setShowRec] = useState(false);

  useEffect(() => {
    const base = index * 2500;
    const t = [
      setTimeout(() => setResalePhase('scanning'),    base + 300),
      setTimeout(() => setRepairPhase('evaluating'),  base + 500),
      setTimeout(() => setGarbagePhase('evaluating'), base + 700),
      setTimeout(() => setGarbagePhase('done'),       base + 2500),
      setTimeout(() => setRepairPhase('done'),        base + 3000),
      setTimeout(() => setResalePhase('done'),        base + 3800),
      setTimeout(() => setShowRec(true),              base + 4500),
    ];
    return () => t.forEach(clearTimeout);
  }, [index]);

  return (
    <motion.div
      className="rp2-universe"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.6, delay: index * 0.3, ease: EASE }}
    >
      <AmbientBlobs colors={[
        'rgba(255,107,107,0.08)',
        'rgba(167,139,250,0.06)',
        'rgba(255,159,67,0.07)',
        'rgba(255,107,157,0.05)',
      ]} />

      <div className="rp2-universe-grid">
        {/* Left: Item hub */}
        <div className="rp2-zone rp2-zone-center">
          <ItemCenter item={item} index={index} totalItems={totalItems} />
        </div>

        {/* Right: All route panels */}
        <div className="rp2-routes-col">
          <div className="rp2-routes-row">
            <RepairPanel item={item} bids={bids} phase={repairPhase} />
            <ResalePanel bids={bids} phase={resalePhase} />
          </div>
          <GarbagePanel bids={bids} phase={garbagePhase} />
        </div>
      </div>

      {/* Recommendation */}
      <AnimatePresence>
        {showRec && decision && (
          <motion.div
            className="rp2-rec"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE }}
          >
            <Sparkles size={16} className="rp2-rec-icon" />
            <span className="rp2-rec-route">
              {decision.best_route === 'sell_as_is' ? 'Direct Resale' :
               decision.best_route === 'repair_then_sell' ? 'Repair & Sell' : 'Trade In'}
            </span>
            <span className="rp2-rec-sep">—</span>
            <span className="rp2-rec-price">${decision.estimated_best_value}</span>
            <span className="rp2-rec-reason">{decision.route_reason}</span>
            <ChevronRight size={15} className="rp2-rec-arrow" />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════
export default function ResearchPage({ items, bids, decisions }) {
  if (!items || items.length === 0) return null;

  const useCarousel = items.length > 1;

  const renderCarouselItem = useCallback((item, index, isActive, isFocused) => (
    <ItemUniverse
      item={item}
      bids={bids[item.item_id] || []}
      decision={decisions[item.item_id]}
      index={index}
      totalItems={items.length}
    />
  ), [bids, decisions, items.length]);

  if (useCarousel) {
    return (
      <div className="rp2-page">
        <div className="research-carousel-wrap">
          <CircularCarousel
            items={items}
            renderItem={renderCarouselItem}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="rp2-page">
      {items.map((item, i) => (
        <ItemUniverse
          key={item.item_id}
          item={item}
          bids={bids[item.item_id] || []}
          decision={decisions[item.item_id]}
          index={i}
          totalItems={items.length}
        />
      ))}
    </div>
  );
}
