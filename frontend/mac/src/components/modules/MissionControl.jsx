import { useState, useMemo, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, useMotionValue } from 'framer-motion';
import {
  Cpu, Eye, Search, RefreshCw, Package, Wrench,
  Trophy, Loader2, DollarSign,
  CheckCircle2, FileText, Image,
  ShoppingBag, TrendingUp,
  ChevronLeft, ChevronRight,
} from 'lucide-react';
import Badge from '../shared/Badge';
import PostingWorkspace from './PostingWorkspace';

/* ────────────────────────────────────────────────────────────────
   Stages + Agents
   ──────────────────────────────────────────────────────────────── */
const STAGES = [
  { id: 1, label: 'Processing', desc: 'Extracting frames, transcribing, and analyzing items',
    agents: [{ id: 'intake', name: 'Intake', icon: Cpu }] },
  { id: 2, label: 'Research', desc: 'Each item has its own fleet of agents racing in parallel',
    agents: [
      { id: 'marketplace_resale', name: 'Resale', icon: Search },
      { id: 'trade_in', name: 'Trade-In', icon: RefreshCw },
      { id: 'return', name: 'Return', icon: Package },
      { id: 'repair_roi', name: 'Repair', icon: Wrench },
    ] },
  { id: 3, label: 'Posting', desc: 'Creating and publishing listings for each item',
    agents: [{ id: 'route_decider', name: 'RouteDecider', icon: Trophy }] },
];

const AGENT_META = {
  marketplace_resale: { name: 'Resale', icon: Search, color: 'var(--primary)' },
  trade_in: { name: 'Trade-In', icon: RefreshCw, color: '#FBBF24' },
  return: { name: 'Return', icon: Package, color: '#A1A1AA' },
  repair_roi: { name: 'Repair', icon: Wrench, color: '#FF6B6B' },
};

const ROUTE_MAP = {
  marketplace_resale: 'sell_as_is', trade_in: 'trade_in',
  repair_roi: 'repair_then_sell', return: 'return',
};

function getStatus(s) {
  if (!s) return 'idle';
  const v = s.status;
  if (
    v === 'agent_started'
    || v === 'thinking'
    || v === 'agent_progress'
    || v === 'queued'
    || v === 'running'
    || v === 'navigating'
    || v === 'filling'
  ) {
    return 'thinking';
  }
  if (v === 'agent_completed' || v === 'done' || v === 'complete') return 'done';
  if (v === 'agent_error' || v === 'error') return 'error';
  return 'idle';
}

function getActiveStageIndex(agents) {
  for (let i = STAGES.length - 1; i >= 0; i--)
    if (STAGES[i].agents.some((a) => getStatus(agents[a.id]) === 'thinking')) return i;
  for (let i = STAGES.length - 1; i >= 0; i--)
    if (STAGES[i].agents.some((a) => getStatus(agents[a.id]) === 'done')) return i;
  return 0;
}

/* ── Small Reusable Bits ──────────────────────────────────────── */
function StatusBadge({ status }) {
  const m = { idle: ['Waiting','mc-badge-idle'], thinking: ['Working','mc-badge-thinking'], done: ['Done','mc-badge-done'], error: ['Error','mc-badge-error'] };
  const [l, c] = m[status] || m.idle;
  return <span className={`mc-badge ${c}`}>{l}</span>;
}

function ProgressBar({ status, progress, doneCount, totalCount }) {
  const pct = status === 'done' ? 100
    : totalCount > 0 ? (doneCount / totalCount) * 100
    : (progress || 0.3) * 100;
  return (
    <div className="mc-card-progress-track">
      <motion.div className={`mc-card-progress-fill ${status === 'done' ? 'done' : ''}`}
        initial={{ width: '0%' }} animate={{ width: `${pct}%` }} transition={{ duration: 0.5 }} />
    </div>
  );
}

/* ── Agent Card — for stages 1, 2, 4 (agent-centric) ─────────── */
function AgentCard({ agent, state, perItem, items, index, children }) {
  const status = getStatus(state);
  const message = state?.message || '';
  const elapsed = state?.elapsed_ms;
  const itemEntries = Object.entries(perItem || {}).filter(([k]) => k !== '_global');
  const doneCount = itemEntries.filter(([, s]) => getStatus(s) === 'done').length;
  const totalCount = Math.max(itemEntries.length, items?.length || 0);

  return (
    <motion.div className={`mc-card mc-card-${status}`}
      initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}>
      <div className="mc-card-header">
        <div className={`mc-card-icon mc-icon-${status}`}><agent.icon size={16} /></div>
        <span className="mc-card-name">{agent.name}</span>
        {totalCount > 1 && status !== 'idle' && (
          <span className="mc-card-item-count">{doneCount}/{totalCount}</span>
        )}
        <StatusBadge status={status} />
        {elapsed && <span className="mc-card-timer">{(elapsed/1000).toFixed(1)}s</span>}
      </div>
      <div className="mc-card-message">
        {status === 'thinking' && <Loader2 size={12} className="mc-spinner" />}
        {message}
      </div>
      {(status === 'thinking' || status === 'done') && (
        <ProgressBar status={status} progress={state?.progress} doneCount={doneCount} totalCount={totalCount} />
      )}
      {items && items.length > 1 && itemEntries.length > 0 && (
        <div className="mc-item-list">
          {items.map((item) => {
            const is = perItem?.[item.item_id];
            if (!is) return null;
            const st = getStatus(is);
            return (
              <div key={item.item_id} className={`mc-item-row mc-item-${st}`}>
                <span className={`mc-item-dot ${st}`} />
                <span className="mc-item-name">{item.name_guess?.split(' ').slice(0, 3).join(' ')}</span>
                {st === 'done' && is.message && <span className="mc-item-msg">{is.message.slice(0, 60)}</span>}
                {st === 'thinking' && <Loader2 size={9} className="mc-spinner" />}
              </div>
            );
          })}
        </div>
      )}
      {children}
    </motion.div>
  );
}

/* ════════════════════════════════════════════════════════════════
   STAGE 3: ITEM-CENTRIC BIDDING DISPLAY
   Each item gets its own card with agents orbiting around it
   ════════════════════════════════════════════════════════════════ */

function FloatingAgentSatellite({ agentId, state, bid, orbitIndex }) {
  const meta = AGENT_META[agentId];
  if (!meta) return null;
  const status = getStatus(state);
  const Icon = meta.icon;
  const hasBid = bid && bid.viable;
  return (
    <motion.div
      className={`sat-agent sat-${status}`}
      initial={{ opacity: 0, scale: 0.7, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ delay: orbitIndex * 0.05, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
      style={{ '--agent-accent': meta.color }}
    >
      <div className={`sat-icon-orb sat-orb-${status}`}>
        {status === 'thinking' && <div className="sat-ripple" />}
        {status === 'thinking' && <div className="sat-ripple sat-ripple-2" />}
        <Icon size={18} />
      </div>
      <span className="sat-name">{meta.name}</span>
      {status === 'done' && hasBid && (
        <motion.span className="sat-value"
          initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}>
          <DollarSign size={11} />{bid.estimated_value?.toFixed(0)}
        </motion.span>
      )}
      {status === 'done' && !hasBid && <span className="sat-na">N/A</span>}
      {status === 'thinking' && (
        <span className="sat-working"><Loader2 size={10} className="mc-spinner" /></span>
      )}
      {status === 'done' && hasBid && bid.confidence != null && (
        <span className="sat-conf">{(bid.confidence * 100).toFixed(0)}%</span>
      )}
      {status === 'error' && <span className="sat-err">!</span>}
    </motion.div>
  );
}

/* ── Orbital positions for comp cards around the planet ── */
const COMP_ORBIT = [
  { x: -55, y: -65 },   // top-left
  { x: 55, y: -65 },    // top-right
  { x: 75, y: 10 },     // right
  { x: 55, y: 85 },     // bottom-right
  { x: -55, y: 85 },    // bottom-left
  { x: -75, y: 10 },    // left
];

function FloatingCompsCloud({ comps }) {
  if (!comps || comps.length === 0) return null;
  return (
    <div className="flt-comps-orbit">
      <div className="flt-comps-label">
        <Search size={11} /> {comps.length} listings found
      </div>
      <div className="flt-comps-ring">
        {comps.slice(0, 6).map((c, ci) => {
          const pos = COMP_ORBIT[ci % COMP_ORBIT.length];
          const baseDelay = 0.5;
          const staggerDelay = baseDelay + ci * 0.05;
          return (
            <motion.div key={ci} className="flt-comp-card"
              initial={{ opacity: 0, scale: 0.6, x: 0, y: 20 }}
              animate={{ opacity: 1, scale: 1, x: 0, y: 0 }}
              transition={{ delay: staggerDelay, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
              style={{ '--orbit-x': `${pos.x}%`, '--orbit-y': `${pos.y}%` }}>
              <div className={`flt-comp-plat plat-${(c.platform || 'other').toLowerCase()}`}>
                {(c.platform || 'other').charAt(0).toUpperCase() + (c.platform || 'other').slice(1)}
              </div>
              {c.image_url ? (
                <div className="flt-comp-img">
                  <img src={c.image_url} alt="" referrerPolicy="no-referrer" loading="lazy"
                    onError={(e) => { e.target.onerror = null; e.target.parentElement.classList.add('ibc-lc-noimg'); e.target.replaceWith(Object.assign(document.createElement('span'), { className: 'ibc-lc-fallback-icon' })); }} />
                </div>
              ) : (
                <div className="flt-comp-img ibc-lc-noimg"><ShoppingBag size={14} /></div>
              )}
              <div className="flt-comp-price">${c.price?.toFixed(0)}</div>
              <div className="flt-comp-title">{c.title}</div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

function FloatingTradeInWidget({ allBids }) {
  const tiBid = allBids.find((b) => b.route_type === 'trade_in' && b.trade_in_quotes?.length > 0);
  if (!tiBid) return null;
  const quotes = [...tiBid.trade_in_quotes].sort((a, b) => b.payout - a.payout);
  const best = quotes[0];
  const others = quotes.slice(1);
  const isApple = best.provider === 'Apple Trade In';

  return (
    <motion.div className="flt-tradein"
      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}>
      <div className="ati-header">
        {isApple && <span className="ati-apple-logo"></span>}
        <span className="ati-title">{isApple ? 'Trade In' : best.provider}</span>
        {best.confidence >= 0.9 && <span className="ati-live-dot" />}
      </div>
      <div className="ati-divider" />
      <div className="ati-payout">${best.payout?.toFixed(0)}</div>
      <div className="ati-detail">
        <span>{best.speed}</span>
        <span className="ati-sep">·</span>
        <span>{best.effort} effort</span>
      </div>
      {others.length > 0 && (
        <div className="ati-others">
          {others.map((q, i) => (
            <div key={i} className="ati-alt-row">
              <span className="ati-alt-name">{q.provider}</span>
              <span className="ati-alt-val">${q.payout?.toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}

function ItemPlanet({ item, itemIndex, agentStates, itemBids, stage3Plan }) {
  const planAgents = stage3Plan?.plan?.[item.item_id]?.agents || Object.keys(AGENT_META);
  const allBids = itemBids || [];

  const activeCount = planAgents.filter((a) => getStatus(agentStates?.[a]) === 'thinking').length;
  const doneCount = planAgents.filter((a) => getStatus(agentStates?.[a]) === 'done').length;
  const allDone = doneCount === planAgents.length && planAgents.length > 0;
  const anyThinking = activeCount > 0;

  const streamingComps = useMemo(() => {
    const resaleBid = allBids.find((b) => b.route_type === 'sell_as_is');
    return resaleBid?.comparable_listings || [];
  }, [allBids]);

  const bestBid = useMemo(() => {
    const viable = allBids.filter((b) => b.viable);
    if (viable.length === 0) return null;
    return viable.reduce((a, b) => (a.estimated_value > b.estimated_value ? a : b));
  }, [allBids]);

  const condition = item.visible_defects?.length || item.spoken_defects?.length
    ? (item.visible_defects?.some?.((d) => d.severity === 'major') ? 'Fair' : 'Good')
    : 'Like New';

  return (
    <motion.div
      className={`planet-system ${anyThinking ? 'planet-active' : ''} ${allDone ? 'planet-done' : ''}`}
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: itemIndex * 0.05, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
    >
      {/* Agent route badges row */}
      <div className="planet-agents-row">
        {planAgents.map((agentId, i) => {
          const routeType = ROUTE_MAP[agentId];
          const bid = allBids.find((b) => b.route_type === routeType);
          return (
            <FloatingAgentSatellite
              key={agentId}
              agentId={agentId}
              state={agentStates?.[agentId]}
              bid={bid}
              orbitIndex={i}
            />
          );
        })}
      </div>

      {/* The Planet — the item itself */}
      <div className={`planet-core ${anyThinking ? 'planet-core-active' : ''} ${allDone ? 'planet-core-done' : ''}`}>
        {item.hero_frame_paths?.[0] ? (
          <img src={item.hero_frame_paths[0]} alt={item.name_guess} className="planet-img" />
        ) : (
          <div className="planet-placeholder"><ShoppingBag size={36} /></div>
        )}
      </div>

      {/* Item label below the planet */}
      <div className="planet-label">
        <span className="planet-name">{item.name_guess}</span>
        <div className="planet-tags">
          <Badge variant={condition === 'Like New' ? 'success' : 'warning'}>{condition}</Badge>
          {allDone && bestBid && (
            <motion.span className="planet-best"
              initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }}>
              <TrendingUp size={12} /> ${bestBid.estimated_value?.toFixed(0)}
            </motion.span>
          )}
          {anyThinking && (
            <span className="planet-scanning">
              <Loader2 size={10} className="mc-spinner" /> {activeCount} active
            </span>
          )}
        </div>
        <div className="planet-progress-ring">
          <svg viewBox="0 0 36 36" className="planet-ring-svg">
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--border)" strokeWidth="2" />
            <motion.circle cx="18" cy="18" r="15.5" fill="none"
              stroke={allDone ? 'var(--success)' : 'var(--primary)'}
              strokeWidth="2" strokeLinecap="round"
              strokeDasharray="97.4"
              initial={{ strokeDashoffset: 97.4 }}
              animate={{ strokeDashoffset: 97.4 - (doneCount / Math.max(planAgents.length, 1)) * 97.4 }}
              transition={{ duration: 0.5 }}
              transform="rotate(-90 18 18)" />
          </svg>
          <span className="planet-ring-text">{doneCount}/{planAgents.length}</span>
        </div>
      </div>

      {/* Marketplace comps surrounding the item */}
      <AnimatePresence>
        {streamingComps.length > 0 && (
          <FloatingCompsCloud comps={streamingComps} />
        )}
      </AnimatePresence>

      {/* Floating trade-in widget */}
      <AnimatePresence>
        {allBids.some((b) => b.route_type === 'trade_in' && b.trade_in_quotes?.length > 0) && (
          <FloatingTradeInWidget allBids={allBids} />
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/* ════════════════════════════════════════════════════════════════
   STAGE-SPECIFIC EMBEDDED CONTENT (1, 2, 4 unchanged)
   ════════════════════════════════════════════════════════════════ */

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

      <motion.button
        className="icr-nav icr-nav-prev"
        disabled={idx === 0}
        onClick={prev}
        whileHover={{ scale: 1.15, backgroundColor: 'var(--bg-card)' }}
        whileTap={{ scale: 0.9 }}
      >
        <ChevronLeft size={16} />
      </motion.button>
      <motion.button
        className="icr-nav icr-nav-next"
        disabled={idx === count - 1}
        onClick={next}
        whileHover={{ scale: 1.15, backgroundColor: 'var(--bg-card)' }}
        whileTap={{ scale: 0.9 }}
      >
        <ChevronRight size={16} />
      </motion.button>

      <div className="icr-dots">
        {frames.map((_, i) => (
          <motion.button
            key={i}
            className={`icr-dot${i === idx ? ' icr-dot-active' : ''}`}
            onClick={() => setIdx(i)}
            whileHover={{ scale: 1.4 }}
            whileTap={{ scale: 0.8 }}
            animate={i === idx ? { scale: 1.3, opacity: 1 } : { scale: 1, opacity: 0.4 }}
            transition={{ type: 'spring', damping: 15, stiffness: 400 }}
          />
        ))}
      </div>
    </div>
  );
}

function ItemDetailModal({ item, onClose }) {
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

  return (
    <motion.div
      className="ide-overlay"
      key="item-detail-modal"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
      onClick={onClose}
    >
      <motion.button
        className="ide-close"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ delay: 0.4, duration: 0.3 }}
        onClick={onClose}
      >
        ×
      </motion.button>

      <div className="ide-canvas" onClick={(e) => e.stopPropagation()}>
        <motion.div
          className="ide-hero"
          initial={{ scale: 0.85, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.9, opacity: 0, y: 10, transition: { duration: 0.3, ease: [0.4, 0, 1, 1] } }}
          transition={{ ...smooth, delay: 0.08 }}
        >
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
            <motion.div
              key={`l-${i}`}
              className="ide-bubble"
              style={{ '--float-dur': `${5 + i * 1.1}s`, '--float-delay': `${i * 0.5}s`, '--float-y': `${-4 - i * 1.5}px` }}
              initial={{ opacity: 0, x: 100, scale: 0.6 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 60, scale: 0.7, transition: { duration: 0.25, delay: i * 0.04, ease: [0.4, 0, 1, 1] } }}
              transition={{ delay: 0.2 + i * 0.09, ...gentle }}
            >
              <div className="ide-bubble-label">{b.label}</div>
              <div className="ide-bubble-value">{b.value}</div>
            </motion.div>
          ))}
        </div>

        <div className="ide-bubbles ide-bubbles-right">
          {rightBubbles.map((b, i) => (
            <motion.div
              key={`r-${i}`}
              className="ide-bubble"
              style={{ '--float-dur': `${5.5 + i * 1}s`, '--float-delay': `${0.3 + i * 0.6}s`, '--float-y': `${-5 - i * 1.5}px` }}
              initial={{ opacity: 0, x: -100, scale: 0.6 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: -60, scale: 0.7, transition: { duration: 0.25, delay: i * 0.04, ease: [0.4, 0, 1, 1] } }}
              transition={{ delay: 0.2 + i * 0.09, ...gentle }}
            >
              <div className="ide-bubble-label">{b.label}</div>
              <div className="ide-bubble-value">{b.value}</div>
            </motion.div>
          ))}
        </div>

        <div className="ide-bottom" />
      </div>
    </motion.div>
  );
}

function IntakeStrip({ state }) {
  const status = getStatus(state);
  const message = state?.message || '';
  const elapsed = state?.elapsed_ms;
  const isDone = status === 'done';

  return (
    <motion.div
      className={`intake-strip intake-strip-${status}`}
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.32, 0.72, 0, 1] }}
    >
      <div className="intake-strip-left">
        {isDone ? (
          <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', damping: 12, stiffness: 400 }}>
            <CheckCircle2 size={14} className="intake-strip-icon-done" />
          </motion.div>
        ) : status === 'thinking' ? (
          <Loader2 size={14} className="mc-spinner" />
        ) : (
          <Cpu size={14} />
        )}
        <span className="intake-strip-msg">{message}</span>
      </div>
      <div className="intake-strip-right">
        {elapsed != null && <span className="intake-strip-time">{(elapsed / 1000).toFixed(1)}s</span>}
      </div>
      {status === 'thinking' && (
        <div className="intake-strip-progress">
          <motion.div className="intake-strip-bar"
            initial={{ width: '0%' }}
            animate={{ width: isDone ? '100%' : '60%' }}
            transition={{ duration: 3, ease: [0.32, 0.72, 0, 1] }}
          />
        </div>
      )}
      {status === 'thinking' && <div className="intake-strip-shimmer" />}
    </motion.div>
  );
}

function SkeletonPulse({ width = '100%', height = 12, radius = 6, style }) {
  return (
    <div className="skeleton-pulse" style={{ width, height, borderRadius: radius, ...style }} />
  );
}

function StreamingText({ text, wordsPerTick = 2, intervalMs = 40 }) {
  const words = useMemo(() => (text || '').split(/\s+/).filter(Boolean), [text]);
  const [count, setCount] = useState(0);

  useEffect(() => {
    setCount(0);
    if (!words.length) return undefined;
    const id = setInterval(() => {
      setCount((c) => {
        if (c >= words.length) {
          clearInterval(id);
          return c;
        }
        const next = Math.min(c + wordsPerTick, words.length);
        if (next >= words.length) clearInterval(id);
        return next;
      });
    }, intervalMs);
    return () => clearInterval(id);
  }, [words, wordsPerTick, intervalMs]);

  const visible = words.slice(0, count).join(' ');
  const done = count >= words.length;

  return (
    <p className="ext-transcript-text">
      {visible}
      {!done && <span className="streaming-cursor" />}
    </p>
  );
}

/** Job is still in the intake / upload pipeline before we necessarily have WS agent state. */
const INTAKE_PHASE_STATUSES = new Set(['processing', 'uploading', 'extracting', 'analyzing']);

function effectiveIntakeState(agentsIntake, job) {
  if (agentsIntake && getStatus(agentsIntake) !== 'idle') return agentsIntake;
  const st = String(job?.status || '').toLowerCase();
  if (job?.job_id && INTAKE_PHASE_STATUSES.has(st)) {
    return {
      status: 'thinking',
      message:
        st === 'uploading'
          ? 'Uploading video…'
          : st === 'extracting'
            ? 'Saving video — preparing analysis…'
            : 'Starting video analysis…',
      progress: 0.05,
    };
  }
  return agentsIntake ?? null;
}

function ProcessingContent({ job, agents, items, miniPlayer }) {
  const intakeState = useMemo(
    () => effectiveIntakeState(agents.intake, job),
    [agents.intake, job?.job_id, job?.status],
  );
  const transcript = intakeState?.transcript_text || job?.transcript_text;
  const framePaths = intakeState?.frame_paths || job?.frame_paths || [];

  const intakeActive = intakeState != null && getStatus(intakeState) !== 'idle';
  const hasFrames = framePaths.length > 0;
  const hasItems = items && items.length > 0;
  const hasTranscript = !!transcript;
  const isWaiting = !hasFrames && !hasItems && !hasTranscript && intakeActive;

  const [selectedItem, setSelectedItem] = useState(null);
  const closeModal = useCallback(() => setSelectedItem(null), []);
  const [hoveredTile, setHoveredTile] = useState(null);

  const E = [0.32, 0.72, 0, 1];
  const spring = { type: 'spring', damping: 24, stiffness: 200 };

  return (
    <div className="mc-embedded pc-flow">
      <AnimatePresence>
        {intakeActive && (
          <motion.div className="pc-strip-row"
            key="intake-strip"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            transition={{ duration: 0.35, delay: 0.05, ease: E }}
          >
            <IntakeStrip state={intakeState || { status: 'thinking', message: 'Working…' }} />
          </motion.div>
        )}
      </AnimatePresence>

      <div className="pc-left">
        {miniPlayer && (
          <motion.div className="pc-player"
            initial={{ opacity: 0, scale: 0.94, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1, ease: E }}
          >
            {miniPlayer}
          </motion.div>
        )}
      </div>

      <div className="pc-right">
        <motion.div className="pc-right-inner" layout transition={{ duration: 0.5, ease: E }}>

          {isWaiting && (
            <motion.div className="pc-section pc-skeleton-group"
              key="skeleton"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.4 }}
            >
              <SkeletonPulse width="40%" height={10} />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 12 }}>
                <SkeletonPulse height={120} radius={12} />
                <SkeletonPulse height={120} radius={12} />
                <SkeletonPulse height={120} radius={12} />
              </div>
              <SkeletonPulse width="60%" height={10} style={{ marginTop: 20 }} />
              <SkeletonPulse width="100%" height={60} radius={12} style={{ marginTop: 8 }} />
            </motion.div>
          )}

          {/* Items on top — pushes everything below */}
          <AnimatePresence>
            {hasItems && (
              <motion.div className="pc-section"
                key="items"
                layout
                initial={{ opacity: 0, y: -16, filter: 'blur(8px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                transition={{ duration: 0.6, ease: E }}
              >
                <motion.div className="pc-section-label"
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.1, duration: 0.4, ease: E }}
                >
                  <ShoppingBag size={12} /> Items Detected
                  <motion.span className="pc-section-count"
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: 0.3, type: 'spring', damping: 12, stiffness: 400 }}
                  >
                    {items.length}
                  </motion.span>
                </motion.div>
                <div className="mc-items-row" style={{ gridTemplateColumns: `repeat(${Math.min(items.length, 3)}, 1fr)` }}>
                  {items.map((item, i) => {
                    const condition = item.visible_defects?.length || item.spoken_defects?.length
                      ? (item.visible_defects?.some?.((d) => d.severity === 'major') ? 'Fair' : 'Good')
                      : 'Like New';
                    const isHovered = hoveredTile === item.item_id;
                    return (
                      <motion.div key={item.item_id} className={`mc-item-tile ${isHovered ? 'mc-tile-hovered' : ''}`}
                        initial={{ opacity: 0, y: 20, scale: 0.92 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        whileHover={{ y: -4, scale: 1.02, transition: { duration: 0.25, ease: E } }}
                        whileTap={{ scale: 0.98 }}
                        transition={{ delay: i * 0.12 + 0.15, ...spring }}
                        onClick={() => setSelectedItem(item)}
                        onHoverStart={() => setHoveredTile(item.item_id)}
                        onHoverEnd={() => setHoveredTile(null)}
                        style={{ cursor: 'pointer' }}>
                        {item.hero_frame_paths?.[0] && (
                          <motion.div className="mc-tile-img"
                            whileHover={{ scale: 1.03 }}
                            transition={{ duration: 0.3, ease: E }}>
                            <img src={item.hero_frame_paths[0]} alt={item.name_guess} />
                            <div className="mc-tile-img-overlay">
                              <Eye size={16} />
                              <span>View Details</span>
                            </div>
                          </motion.div>
                        )}
                        <div className="mc-tile-header">
                          <span className="mc-tile-name">{item.name_guess}</span>
                          <motion.span
                            className={`mc-cond-pill ${condition === 'Like New' ? 'mc-cond-mint' : condition === 'Fair' ? 'mc-cond-fair' : 'mc-cond-good'}`}
                            initial={{ opacity: 0, scale: 0.9 }}
                            animate={{ opacity: 1, scale: 1 }}
                            transition={{ delay: i * 0.12 + 0.4, duration: 0.5, ease: E }}
                          >
                            {condition}
                          </motion.span>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Transcript — pushes frames down when it arrives */}
          <AnimatePresence>
            {hasTranscript && (
              <motion.div className="pc-section"
                key="transcript"
                layout
                initial={{ opacity: 0, y: -16, filter: 'blur(6px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                transition={{ duration: 0.5, ease: E }}
              >
                <div className="ext-transcript">
                  <div className="ext-transcript-label"><FileText size={12} /> Transcript</div>
                  <StreamingText text={transcript} wordsPerTick={1} intervalMs={100} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Frames — at the bottom, pushed down by transcript & items */}
          <AnimatePresence>
            {hasFrames && (
              <motion.div className="pc-section" style={{ marginTop: 10 }}
                key="filmstrip"
                layout
                initial={{ opacity: 0, y: -16, filter: 'blur(6px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                transition={{ duration: 0.5, ease: E }}
              >
                <div className="ext-filmstrip">
                  <div className="ext-filmstrip-label"><Image size={12} /> {framePaths.length} frame{framePaths.length !== 1 ? 's' : ''} extracted</div>
                  <div className="ext-filmstrip-rail filmstrip-grid">
                    <AnimatePresence>
                      {framePaths.map((fp, i) => (
                        <motion.div key={fp} className="ext-frame"
                          layout
                          initial={{ opacity: 0, scale: 0.5, y: 12, filter: 'blur(4px)' }}
                          animate={{ opacity: 1, scale: 1, y: 0, filter: 'blur(0px)' }}
                          exit={{ opacity: 0, scale: 0.8 }}
                          whileHover={{ scale: 1.05, y: -2, transition: { duration: 0.2 } }}
                          transition={{ type: 'spring', damping: 20, stiffness: 260 }}>
                          <img src={fp} alt={`Frame ${i + 1}`} />
                          <span className="ext-frame-num">{i + 1}</span>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

        </motion.div>
      </div>

      {createPortal(
        <AnimatePresence>
          {selectedItem && (
            <ItemDetailModal item={selectedItem} onClose={closeModal} />
          )}
        </AnimatePresence>,
        document.body
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════
   MAIN MISSION CONTROL
   ════════════════════════════════════════════════════════════════ */
export default function MissionControl({
  agents = {}, agentsRaw = {}, agentsByItem = {},
  stage3Plan, items = [], decisions = {}, bids = {},
  job = null, listings = {}, onExecuteItem, overrideStageIdx,
  postingStatus = {},
  v2Agents = {}, screenshots,
  miniPlayer,
  prefetchResearch = false,
}) {
  const autoIdx = getActiveStageIndex(agents);
  const activeIdx = overrideStageIdx != null ? Math.min(overrideStageIdx, STAGES.length - 1) : autoIdx;

  const stage3TaskCount = useMemo(() => {
    if (!stage3Plan?.plan) return { total: 0, active: 0, done: 0 };
    let total = 0, active = 0, done = 0;
    for (const [itemId, plan] of Object.entries(stage3Plan.plan)) {
      const itemAgents = agentsByItem[itemId] || {};
      for (const agentId of plan.agents) {
        total++;
        const s = getStatus(itemAgents[agentId]);
        if (s === 'thinking') active++;
        if (s === 'done') done++;
      }
    }
    return { total, active, done };
  }, [stage3Plan, agentsByItem]);

  const mountResearch = activeIdx === 1 || (prefetchResearch && activeIdx === 0);

  const researchBody = (
    <>
      {stage3TaskCount.total > 0 && (
        <div className="mc-stage3-counter">
          <span className="mc-s3-badge">
            {stage3TaskCount.active > 0 ? (
              <><Loader2 size={11} className="mc-spinner" /> {stage3TaskCount.active} active</>
            ) : (
              <><CheckCircle2 size={11} /> {stage3TaskCount.done} done</>
            )}
          </span>
          <span className="mc-s3-total">
            {stage3TaskCount.done}/{stage3TaskCount.total} agent-tasks
          </span>
        </div>
      )}
      <div className="planets-field">
        {items.map((item, i) => (
          <ItemPlanet
            key={item.item_id}
            item={item}
            itemIndex={i}
            agentStates={agentsByItem[item.item_id] || {}}
            itemBids={bids[item.item_id] || []}
            stage3Plan={stage3Plan}
          />
        ))}
        {items.length === 0 && (
          <div className="planets-empty">Waiting for items from Stage 1...</div>
        )}
      </div>
    </>
  );

  return (
    <div className="mission-control-v2">
      <div className="mc-stage-scroll-area">
        <AnimatePresence mode="wait">
          {activeIdx === 0 && (
            <motion.div key="mc-stage-1" className="mc-stage-content"
              initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -50 }} transition={{ duration: 0.25 }}>

              {!(miniPlayer) && (
                <div className={`mc-agents-row mc-agents-${STAGES[0].agents.length}`}>
                  {STAGES[0].agents.map((agent, i) => (
                    <AgentCard key={agent.id} agent={agent} state={agents[agent.id]}
                      perItem={agentsRaw[agent.id] || {}} items={items} index={i}>
                    </AgentCard>
                  ))}
                </div>
              )}

              <ProcessingContent job={job} agents={agents} items={items} miniPlayer={miniPlayer} />
            </motion.div>
          )}
        </AnimatePresence>

        {mountResearch && (
          <div
            className={`mc-research-layer ${activeIdx === 1 ? 'mc-research-visible' : 'mc-research-prefetch'}`}
            aria-hidden={activeIdx !== 1}
          >
            <motion.div
              className="mc-stage-content"
              initial={false}
              animate={{ opacity: activeIdx === 1 ? 1 : 0 }}
              transition={{ duration: 0.2 }}
            >
              {researchBody}
            </motion.div>
          </div>
        )}

        <AnimatePresence mode="wait">
          {activeIdx === 2 && (
            <motion.div key="mc-stage-3" className="mc-stage-content"
              initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -50 }} transition={{ duration: 0.25 }}>
              <PostingWorkspace items={items} decisions={decisions} postingStatus={postingStatus} v2Agents={v2Agents} screenshots={screenshots} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
