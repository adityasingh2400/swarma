import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import BrowserFeed from '../BrowserFeed';
import FocusMode from '../FocusMode';
import {
  Search, TrendingUp, CheckCircle2,
  Sparkles, Package, ChevronRight,
} from 'lucide-react';
import { ACTIVE_STATUSES, STATUS_COMPLETE } from '../../utils/contracts';

const EASE = [0.32, 0.72, 0, 1];
const SPRING = { type: 'spring', damping: 25, stiffness: 200 };

const PLATFORM_META = {
  facebook: { label: 'Facebook', color: '#FF9F43' },
  depop:    { label: 'Depop',    color: '#FF2300' },
  amazon:   { label: 'Amazon',   color: '#FF9900' },
};

const RESEARCH_PLATFORMS = ['facebook', 'depop', 'amazon'];

function getScreenshot(screenshots, agentId) {
  if (!screenshots || !agentId) return null;
  if (screenshots instanceof Map) return screenshots.get(agentId)?.url || null;
  return screenshots[agentId]?.url || null;
}

// ── Animated price counter ───────────────────────────
function AnimatedPrice({ value, delay = 0 }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => {
      const end = value;
      const dur = 600;
      const start = performance.now();
      const tick = (now) => {
        const p = Math.min((now - start) / dur, 1);
        setDisplay(Math.round(end * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, delay * 1000);
    return () => clearTimeout(t);
  }, [value, delay]);
  return <span>${display}</span>;
}

// ── Single agent feed tile ───────────────────────────
function AgentTile({ platform, agentId, screenshots, v2Agents, onClick }) {
  const meta = PLATFORM_META[platform] || PLATFORM_META.facebook;
  const shot = getScreenshot(screenshots, agentId);
  const agent = v2Agents?.[agentId];
  const isActive = agent && ACTIVE_STATUSES.has(agent.status);
  const isDone = agent?.status === STATUS_COMPLETE;

  return (
    <motion.div
      className="rp2-agent-tile"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
      onClick={() => onClick?.(agentId)}
      whileHover={{ scale: 1.02, y: -2 }}
      style={{ cursor: 'pointer' }}
    >
      {/* Platform label */}
      <div className="rp2-agent-head">
        <div className="rp2-agent-dot" style={{ background: meta.color }} />
        <span className="rp2-agent-name">{meta.label}</span>
        {isActive && (
          <motion.span
            className="rp2-agent-live"
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          >
            LIVE
          </motion.span>
        )}
        {isDone && (
          <span className="rp2-agent-done"><CheckCircle2 size={10} /> Done</span>
        )}
        {!agent && !shot && (
          <motion.span
            className="rp2-agent-waiting"
            animate={{ opacity: [0.3, 0.7, 0.3] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          >
            Loading...
          </motion.span>
        )}
      </div>

      {/* Browser feed */}
      <div className="rp2-agent-feed">
        {shot ? (
          <BrowserFeed screenshotUrl={shot} size="thumbnail" />
        ) : (
          <div className="rp2-agent-placeholder">
            <Search size={20} />
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ── One item with its 3 orbiting agent feeds ─────────
function ItemResearchCard({ item, index, totalItems, v2Agents, screenshots, decision, onFocusAgent }) {
  const itemId = item?.item_id || '';
  const prefix = itemId.slice(0, 6) || itemId;
  const hasDamage = item.visible_defects?.length > 0;

  const allDone = useMemo(() => {
    return RESEARCH_PLATFORMS.every(p => {
      const agent = v2Agents?.[`${p}-research-${prefix}`];
      return agent?.status === STATUS_COMPLETE;
    });
  }, [v2Agents, prefix]);

  return (
    <motion.div
      className="rp2-card"
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, delay: index * 0.15, ease: EASE }}
    >
      {/* ── Item hero (center) ── */}
      <div className="rp2-card-hero">
        <div className="rp2-card-glow" />
        <div className="rp2-card-img">
          {item.hero_frame_paths?.[0] ? (
            <img src={item.hero_frame_paths[0]} alt={item.name_guess} />
          ) : (
            <div className="rp2-card-img-ph"><Package size={28} /></div>
          )}
        </div>
        <h3 className="rp2-card-name">{item.name_guess}</h3>
        <div className="rp2-card-tags">
          <span className={`rp2-cond-tag ${hasDamage ? 'rp2-cond-warn' : 'rp2-cond-good'}`}>
            {item.condition || (hasDamage ? 'Minor wear' : 'Excellent')}
          </span>
          {totalItems > 1 && (
            <span className="rp2-card-idx">{index + 1}/{totalItems}</span>
          )}
        </div>
      </div>

      {/* ── 3 agent feeds ── */}
      <div className="rp2-card-agents">
        {RESEARCH_PLATFORMS.map((platform, i) => (
          <AgentTile
            key={platform}
            platform={platform}
            agentId={`${platform}-research-${prefix}`}
            screenshots={screenshots}
            v2Agents={v2Agents}
            onClick={onFocusAgent}
          />
        ))}
      </div>

      {/* ── Result summary (appears when all agents done) ── */}
      <AnimatePresence>
        {allDone && decision && (
          <motion.div
            className="rp2-card-result"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4, ease: EASE }}
          >
            <Sparkles size={14} className="rp2-result-icon" />
            <span className="rp2-result-route">
              {decision.best_route === 'sell_as_is' ? 'Direct Resale' :
               decision.best_route === 'repair_then_sell' ? 'Repair & Sell' : 'Best Route'}
            </span>
            <span className="rp2-result-price">
              <AnimatedPrice value={decision.estimated_best_value || 0} delay={0.3} />
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Main page ────────────────────────────────────────
export default function ResearchPage({ items, bids, decisions, v2Agents, screenshots, send }) {
  const [focusedAgentId, setFocusedAgentId] = useState(null);

  if (!items || items.length === 0) return null;

  const focusedAgent = focusedAgentId ? (v2Agents || {})[focusedAgentId] : null;
  const focusedShot = focusedAgentId ? getScreenshot(screenshots, focusedAgentId) : null;

  return (
    <div className="rp2-page">
      {/* Header */}
      <motion.div
        className="rp2-header"
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: EASE }}
      >
        <TrendingUp size={16} />
        <span>Market Research</span>
        <span className="rp2-header-count">
          {items.length} {items.length === 1 ? 'item' : 'items'} · {items.length * 3} agents
        </span>
      </motion.div>

      {/* Item cards grid */}
      <div className={`rp2-grid rp2-grid-${Math.min(items.length, 3)}`}>
        {items.map((item, i) => (
          <ItemResearchCard
            key={item.item_id}
            item={item}
            index={i}
            totalItems={items.length}
            v2Agents={v2Agents}
            screenshots={screenshots}
            decision={decisions[item.item_id]}
            onFocusAgent={setFocusedAgentId}
          />
        ))}
      </div>

      {/* Focus mode overlay */}
      <FocusMode
        agent={focusedAgent}
        screenshotUrl={focusedShot}
        onClose={() => setFocusedAgentId(null)}
        send={send}
      />
    </div>
  );
}
