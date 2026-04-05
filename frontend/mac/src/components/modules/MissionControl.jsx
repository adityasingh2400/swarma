import { useState, useMemo, useEffect, useCallback } from 'react';
import { motion, AnimatePresence, useMotionValue } from 'framer-motion';
import {
  Cpu, Eye, Search, RefreshCw, Package, Wrench,
  Trophy, MessageSquare, Loader2, DollarSign, XCircle,
  CheckCircle2, FileText, AlertTriangle, Image, Zap,
  ShoppingBag, RotateCcw, Clock, TrendingUp, X,
  ChevronLeft, ChevronRight,
} from 'lucide-react';
import Badge from '../shared/Badge';
import AnimatedValue from '../shared/AnimatedValue';

/* ────────────────────────────────────────────────────────────────
   Stages + Agents
   ──────────────────────────────────────────────────────────────── */
const STAGES = [
  { id: 1, label: 'Processing', desc: 'Extracting frames, transcribing, and analyzing items',
    agents: [{ id: 'intake', name: 'Intake', icon: Cpu }] },
  { id: 2, label: 'Route Bidding', desc: 'Each item has its own fleet of agents racing in parallel',
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

const ROUTE_LABELS = {
  sell_as_is: 'Sell As-Is', trade_in: 'Trade-In', repair_then_sell: 'Repair & Sell',
  return: 'Return', no_action: 'No Action',
};
const ROUTE_ICONS = {
  sell_as_is: ShoppingBag, trade_in: RefreshCw, repair_then_sell: Wrench,
  return: RotateCcw, no_action: XCircle,
};
const ROUTE_MAP = {
  marketplace_resale: 'sell_as_is', trade_in: 'trade_in',
  repair_roi: 'repair_then_sell', return: 'return',
};

function getStatus(s) {
  if (!s) return 'idle';
  const v = s.status;
  if (v === 'agent_started' || v === 'thinking' || v === 'agent_progress') return 'thinking';
  if (v === 'agent_completed' || v === 'done') return 'done';
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

function ItemPlanet({ item, itemIndex, totalItems, agentStates, itemBids, stage3Plan }) {
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

  return (
    <>
      <motion.div
        className="idm-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.3 }}
        onClick={onClose}
      />
      <motion.div
        className="idm-container"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <motion.div
          className="idm-panel"
          initial={{ scale: 0.92, y: 30, opacity: 0, filter: 'blur(8px)' }}
          animate={{ scale: 1, y: 0, opacity: 1, filter: 'blur(0px)' }}
          exit={{ scale: 0.95, y: 16, opacity: 0, filter: 'blur(4px)', transition: { duration: 0.2, ease: E } }}
          transition={{ type: 'spring', damping: 28, stiffness: 280 }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="idm-header">
            <motion.h3 className="idm-title"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.15, duration: 0.4, ease: E }}
            >
              {item.name_guess}
            </motion.h3>
            <motion.button
              className="idm-close"
              onClick={onClose}
              whileHover={{ rotate: 90, scale: 1.1, backgroundColor: 'var(--bg-elevated)' }}
              whileTap={{ scale: 0.9 }}
              transition={{ duration: 0.2 }}
            >
              <X size={18} />
            </motion.button>
          </div>

          {frames.length > 0 && (
            <motion.div className="idm-carousel"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.1, duration: 0.5, ease: E }}
            >
              <ItemCarousel frames={frames} alt={item.name_guess} />
            </motion.div>
          )}

          <div className="idm-details">
            <motion.div className="idm-row"
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2, duration: 0.35, ease: E }}>
              <span className="idm-label">Condition</span>
              <Badge variant={condition === 'Like New' ? 'success' : 'warning'}>{condition}</Badge>
            </motion.div>

            {item.confidence != null && (
              <motion.div className="idm-row"
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.25, duration: 0.35, ease: E }}>
                <span className="idm-label">Confidence</span>
                <span className="idm-value">{(item.confidence * 100).toFixed(0)}%</span>
              </motion.div>
            )}

            {item.visible_defects?.length > 0 && (
              <motion.div className="idm-section"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3, duration: 0.4, ease: E }}>
                <span className="idm-label">Visible Defects</span>
                <div className="idm-defects-list">
                  {item.visible_defects.map((d, i) => (
                    <motion.div key={i} className="idm-defect"
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.35 + i * 0.06, duration: 0.3, ease: E }}>
                      <AlertTriangle size={12} />
                      <span>{d.description || d}</span>
                      {d.severity && <Badge variant={d.severity === 'major' ? 'danger' : 'warning'}>{d.severity}</Badge>}
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}

            {item.spoken_defects?.length > 0 && (
              <motion.div className="idm-section"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35, duration: 0.4, ease: E }}>
                <span className="idm-label">Mentioned by Seller</span>
                <div className="idm-defects-list">
                  {item.spoken_defects.map((d, i) => (
                    <motion.div key={i} className="idm-defect"
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.4 + i * 0.06, duration: 0.3, ease: E }}>
                      <MessageSquare size={12} />
                      <span>{typeof d === 'string' ? d : d.description}</span>
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </>
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

function ProcessingContent({ job, agents, items, miniPlayer, settled }) {
  const intakeState = agents.intake;
  const transcript = intakeState?.transcript_text || job?.transcript_text;
  const framePaths = intakeState?.frame_paths || job?.frame_paths || [];

  const intakeActive = getStatus(intakeState) !== 'idle';
  const hasFrames = settled && framePaths.length > 0;
  const hasItems = settled && items && items.length > 0;
  const hasTranscript = settled && !!transcript;
  const isWaiting = settled && !hasFrames && !hasItems && !hasTranscript;

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
            <IntakeStrip state={intakeState} />
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
                          <Badge variant={condition === 'Like New' ? 'success' : 'warning'}>{condition}</Badge>
                        </div>
                        {item.visible_defects?.length > 0 && (
                          <div className="mc-tile-defects">
                            <AlertTriangle size={10} /> {item.visible_defects.map((d) => d.description || d).join(', ')}
                          </div>
                        )}
                      </motion.div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

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
                  <p className="ext-transcript-text">{transcript}</p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {hasFrames && (
              <motion.div className="pc-section"
                key="filmstrip"
                layout
                initial={{ opacity: 0, y: -16, filter: 'blur(6px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                transition={{ duration: 0.5, ease: E }}
              >
                <div className="ext-filmstrip">
                  <div className="ext-filmstrip-label"><Image size={12} /> {framePaths.length} frames extracted</div>
                  <div className="ext-filmstrip-rail filmstrip-grid" style={{ gridTemplateColumns: `repeat(${Math.min(framePaths.length, 4)}, 1fr)` }}>
                    {framePaths.map((fp, i) => (
                      <motion.div key={i} className="ext-frame"
                        initial={{ opacity: 0, scale: 0.85, y: 8 }}
                        animate={{ opacity: 1, scale: 1, y: 0 }}
                        whileHover={{ scale: 1.05, y: -2, transition: { duration: 0.2 } }}
                        transition={{ delay: i * 0.06 + 0.1, duration: 0.35, ease: E }}>
                        <img src={fp} alt={`Frame ${i + 1}`} />
                        <span className="ext-frame-num">{i + 1}</span>
                      </motion.div>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

        </motion.div>
      </div>

      <AnimatePresence>
        {selectedItem && (
          <ItemDetailModal item={selectedItem} onClose={closeModal} />
        )}
      </AnimatePresence>
    </div>
  );
}

function DecisionContent({ decisions, items, onExecuteItem }) {
  const decisionList = Object.values(decisions);
  if (decisionList.length === 0) return null;

  const totalValue = decisionList.reduce((sum, d) => sum + (d.estimated_best_value || 0), 0);

  const TRIFECTA_POS = [
    'trifecta-top',
    'trifecta-bottom-left',
    'trifecta-bottom-right',
  ];

  const itemsWithDecisions = items.filter((item) => decisions[item.item_id]);

  return (
    <div className="mc-embedded">
      <div className="decision-trifecta">
        {/* Central Decider Hub */}
        <motion.div className="dt-hub"
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4, ease: [0.32, 0.72, 0, 1] }}>
          <div className="dt-hub-glow" />
          <div className="dt-hub-inner">
            <div className="dt-hub-icon-ring">
              <Trophy size={24} />
            </div>
            <div className="dt-hub-label">Route Decider</div>
            <div className="dt-hub-total">
              <span className="dt-hub-total-label">Total Recovery</span>
              <AnimatedValue value={totalValue} prefix="$" decimals={2} large positive />
            </div>
            <div className="dt-hub-items">
              {itemsWithDecisions.map((item) => {
                const d = decisions[item.item_id];
                const Icon = ROUTE_ICONS[d.best_route] || Trophy;
                return (
                  <div key={item.item_id} className="dt-hub-item-row">
                    <Icon size={12} />
                    <span className="dt-hub-item-name">{item.name_guess?.split(' ').slice(0, 3).join(' ')}</span>
                    <span className="dt-hub-item-route">{ROUTE_LABELS[d.best_route]}</span>
                    <span className="dt-hub-item-val">${d.estimated_best_value?.toFixed(0)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </motion.div>

        {/* Connector lines (SVG) */}
        <svg className="dt-connectors" viewBox="0 0 800 600" preserveAspectRatio="none">
          {itemsWithDecisions.map((_, i) => {
            const paths = [
              'M 400 200 Q 400 80 400 40',
              'M 320 280 Q 160 360 120 440',
              'M 480 280 Q 640 360 680 440',
            ];
            return (
              <motion.path key={i} d={paths[i % 3]} className="dt-conn-line"
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ delay: 0.3 + i * 0.15, duration: 0.6, ease: 'easeOut' }} />
            );
          })}
        </svg>

        {/* Route Cards in trifecta positions */}
        {itemsWithDecisions.slice(0, 3).map((item, i) => {
          const d = decisions[item.item_id];
          const Icon = ROUTE_ICONS[d.best_route] || Trophy;
          const posClass = TRIFECTA_POS[i % 3];

          const routes = (() => {
            if (!d.alternatives) return [];
            const seen = new Set();
            return [d.winning_bid, ...d.alternatives]
              .filter(Boolean)
              .filter((r) => { if (seen.has(r.route_type)) return false; seen.add(r.route_type); return true; })
              .filter((r) => r.viable !== false)
              .slice(0, 3);
          })();

          return (
            <motion.div key={item.item_id}
              className={`dt-card ${posClass}`}
              initial={{ opacity: 0, scale: 0.85, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ delay: 0.2 + i * 0.05, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}>
              <div className="dt-card-top">
                {item.hero_frame_paths?.[0] && (
                  <img src={item.hero_frame_paths[0]} alt={item.name_guess} className="dt-card-thumb" />
                )}
                <div className="dt-card-meta">
                  <span className="dt-card-name">{item.name_guess}</span>
                  <Badge variant="success">{ROUTE_LABELS[d.best_route] || d.best_route}</Badge>
                </div>
              </div>
              <div className="dt-card-value">
                <Icon size={18} />
                <AnimatedValue value={d.estimated_best_value || 0} prefix="$" decimals={2} positive />
              </div>
              {d.route_reason && <div className="dt-card-reason">{d.route_reason}</div>}
              {routes.length > 0 && (
                <div className="dt-card-routes">
                  {routes.map((route, ri) => {
                    const RouteIcon = ROUTE_ICONS[route.route_type] || TrendingUp;
                    return (
                      <div key={route.route_type} className={`dt-card-route ${ri === 0 ? 'winner' : ''}`}>
                        <RouteIcon size={12} />
                        <span className="dt-card-route-label">{ROUTE_LABELS[route.route_type] || route.route_type}</span>
                        <span className="dt-card-route-val">${route.estimated_value?.toFixed(0)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
              <button className="dt-card-execute" onClick={() => onExecuteItem?.(item.item_id, ['ebay', 'mercari'])}>
                <Zap size={13} /> Execute Route
              </button>
            </motion.div>
          );
        })}

        {/* Overflow items (4+) in a row below */}
        {itemsWithDecisions.length > 3 && (
          <div className="dt-overflow">
            {itemsWithDecisions.slice(3).map((item, i) => {
              const d = decisions[item.item_id];
              const Icon = ROUTE_ICONS[d.best_route] || Trophy;
              return (
                <motion.div key={item.item_id} className="dt-card dt-overflow-card"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.5 + i * 0.05, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}>
                  <div className="dt-card-top">
                    {item.hero_frame_paths?.[0] && (
                      <img src={item.hero_frame_paths[0]} alt={item.name_guess} className="dt-card-thumb" />
                    )}
                    <div className="dt-card-meta">
                      <span className="dt-card-name">{item.name_guess}</span>
                      <Badge variant="success">{ROUTE_LABELS[d.best_route] || d.best_route}</Badge>
                    </div>
                  </div>
                  <div className="dt-card-value">
                    <Icon size={18} />
                    <AnimatedValue value={d.estimated_best_value || 0} prefix="$" decimals={2} positive />
                  </div>
                  <button className="dt-card-execute" onClick={() => onExecuteItem?.(item.item_id, ['ebay', 'mercari'])}>
                    <Zap size={13} /> Execute Route
                  </button>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
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
  miniPlayer, settled,
}) {
  const autoIdx = getActiveStageIndex(agents);
  const activeIdx = overrideStageIdx != null ? Math.min(overrideStageIdx, STAGES.length - 1) : autoIdx;

  const stage = STAGES[activeIdx];

  // Count total concurrent tasks for Stage 3 header
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

  return (
    <div className="mission-control-v2">
      <div className="mc-stage-scroll-area">
        <AnimatePresence mode="wait">
          <motion.div key={stage.id} className="mc-stage-content"
            initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -50 }} transition={{ duration: 0.25 }}>

            {stage.id === 2 && stage3TaskCount.total > 0 && (
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

            {stage.id === 2 ? (
              <div className="planets-field">
                {items.map((item, i) => (
                  <ItemPlanet
                    key={item.item_id}
                    item={item}
                    itemIndex={i}
                    totalItems={items.length}
                    agentStates={agentsByItem[item.item_id] || {}}
                    itemBids={bids[item.item_id] || []}
                    stage3Plan={stage3Plan}
                  />
                ))}
                {items.length === 0 && (
                  <div className="planets-empty">Waiting for items from Stage 1...</div>
                )}
              </div>
            ) : (stage.id === 1 && miniPlayer) ? null : (
              <div className={`mc-agents-row mc-agents-${stage.agents.length}`}>
                {stage.agents.map((agent, i) => (
                  <AgentCard key={agent.id} agent={agent} state={agents[agent.id]}
                    perItem={agentsRaw[agent.id] || {}} items={items} index={i}>
                  </AgentCard>
                ))}
              </div>
            )}

            {stage.id === 1 && <ProcessingContent job={job} agents={agents} items={items} miniPlayer={miniPlayer} settled={settled} />}
            {stage.id === 3 && <DecisionContent decisions={decisions} items={items} onExecuteItem={onExecuteItem} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
