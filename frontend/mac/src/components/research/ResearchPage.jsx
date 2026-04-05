import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import BrowserFeed from '../BrowserFeed';
import FocusMode from '../FocusMode';
import {
  Search, TrendingUp, CheckCircle2, DollarSign,
  Package,
} from 'lucide-react';
import {
  ACTIVE_STATUSES,
  STATUS_COMPLETE,
  STATUS_QUEUED,
  PHASE_RESEARCH,
} from '../../utils/contracts';

/** Focus overlay needs an agent shape; WS may lag behind screenshot thumbnails. */
function resolveAgentForFocus(agentId, v2Agents) {
  if (!agentId) return null;
  const existing = v2Agents?.[agentId];
  if (existing && typeof existing === 'object') return existing;
  const m = String(agentId).match(/^(facebook|depop|amazon)-research-(.+)$/i);
  const platform = m ? m[1].toLowerCase() : 'research';
  return {
    agent_id: agentId,
    platform,
    phase: PHASE_RESEARCH,
    status: STATUS_QUEUED,
    task: 'Market research…',
    started_at: null,
  };
}

const EASE = [0.32, 0.72, 0, 1];
const SPRING = { type: 'spring', damping: 25, stiffness: 200 };

const PLATFORM_META = {
  facebook: { label: 'Facebook', color: '#FF9F43' },
  depop:    { label: 'Depop',    color: '#FF2300' },
  amazon:   { label: 'Amazon',   color: '#FF9900' },
};

const RESEARCH_PLATFORMS = ['facebook', 'depop', 'amazon'];

/** Parse agent:result / final_result (JSON string or object) for playbook avg_sold_price. */
function extractPlatformResearchPrice(agent) {
  const raw = agent?.result;
  if (raw == null) return null;
  let obj = raw;
  if (typeof raw === 'string') {
    try {
      obj = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (typeof obj !== 'object' || !obj) return null;
  const v = obj.avg_sold_price ?? obj.avg_active_price ?? obj.median_price;
  return typeof v === 'number' && v > 0 ? v : null;
}

/** When route decision isn't in state yet (common with multiple items), build prices from research agents. */
function valuationFromResearchAgents(itemId, v2Agents) {
  const prices = {};
  for (const p of RESEARCH_PLATFORMS) {
    const agent = v2Agents?.[`${p}-research-${itemId}`];
    if (!agent || agent.status !== STATUS_COMPLETE) continue;
    const price = extractPlatformResearchPrice(agent);
    if (price != null) prices[p] = price;
  }
  const vals = Object.values(prices).filter((n) => n > 0);
  if (vals.length === 0) return null;
  return {
    prices,
    estimated_best_value: Math.max(...vals),
  };
}

function decisionHasPrices(decision) {
  if (!decision?.prices || typeof decision.prices !== 'object') return false;
  return Object.values(decision.prices).some((v) => typeof v === 'number' && v > 0);
}

function mergeDecisionForValuation(decision, researchValuation) {
  if (decisionHasPrices(decision)) return decision;
  if (!researchValuation) return null;
  return {
    ...(decision || {}),
    prices: { ...(decision?.prices || {}), ...researchValuation.prices },
    estimated_best_value: researchValuation.estimated_best_value,
  };
}

function getScreenshot(screenshots, agentId) {
  if (!screenshots || !agentId) return null;
  const want = String(agentId).trim();
  const wantLower = want.toLowerCase();
  if (screenshots instanceof Map) {
    const hit = screenshots.get(want) ?? screenshots.get(agentId);
    if (hit?.url) return hit.url;
    for (const [k, v] of screenshots.entries()) {
      if (k && String(k).trim().toLowerCase() === wantLower) return v?.url ?? null;
    }
    return null;
  }
  const o = screenshots[want] ?? screenshots[agentId];
  if (o?.url) return o.url;
  for (const k of Object.keys(screenshots)) {
    if (k && k.toLowerCase() === wantLower) return screenshots[k]?.url ?? null;
  }
  return null;
}

// ── Animated price counter ───────────────────────────
function AnimatedPrice({ value, delay = 0, prefix = '$' }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (!value) return;
    const t = setTimeout(() => {
      const dur = 800;
      const start = performance.now();
      const tick = (now) => {
        const p = Math.min((now - start) / dur, 1);
        setDisplay(Math.round(value * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, delay * 1000);
    return () => clearTimeout(t);
  }, [value, delay]);
  return <span>{prefix}{display}</span>;
}

// ── Single agent feed tile ───────────────────────────
function AgentTile({ platform, agentId, screenshots, v2Agents, onClick }) {
  const meta = PLATFORM_META[platform] || PLATFORM_META.facebook;
  const shot = getScreenshot(screenshots, agentId);
  const agent = v2Agents?.[agentId];
  const isActive = agent && ACTIVE_STATUSES.has(agent.status);
  const isDone = agent?.status === STATUS_COMPLETE;

  const activate = useCallback(() => {
    onClick?.(agentId);
  }, [onClick, agentId]);

  return (
    <motion.div
      className="rp2-agent-tile"
      role="button"
      tabIndex={0}
      aria-label={`Open ${meta.label} research view`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
      onClick={(e) => {
        e.stopPropagation();
        activate();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          activate();
        }
      }}
      whileHover={{ scale: 1.02, y: -2 }}
      whileTap={{ scale: 0.98 }}
      style={{ cursor: 'pointer' }}
    >
      <div className="rp2-agent-head">
        <div className="rp2-agent-dot" style={{ background: meta.color }} />
        <span className="rp2-agent-name">{meta.label}</span>
        {isActive && (
          <span className="rp2-agent-live rp2-agent-live--pulse">LIVE</span>
        )}
        {isDone && (
          <span className="rp2-agent-done"><CheckCircle2 size={10} /> Done</span>
        )}
        {!agent && !shot && (
          <span className="rp2-agent-waiting rp2-agent-waiting--pulse">Loading...</span>
        )}
      </div>
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

// ── Valuation card — shows after all agents complete ─
function ValuationCard({ decision, item }) {
  if (!decision) return null;

  const prices = decision.prices || {};
  const bestValue = decision.estimated_best_value || 0;
  const platforms = Object.entries(prices)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);

  return (
    <motion.div
      className="rp2-valuation"
      initial={{ opacity: 0, y: 16, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, ease: EASE }}
    >
      <div className="rp2-val-header">
        <DollarSign size={14} />
        <span>Market Valuation</span>
      </div>

      <div className="rp2-val-platforms">
        {platforms.map(([platform, price], i) => {
          const meta = PLATFORM_META[platform] || {};
          return (
            <motion.div
              key={platform}
              className="rp2-val-row"
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.15 + i * 0.12, duration: 0.35, ease: EASE }}
            >
              <div className="rp2-val-dot" style={{ background: meta.color }} />
              <span className="rp2-val-platform">{meta.label || platform}</span>
              <span className="rp2-val-price">
                <AnimatedPrice value={Math.round(price)} delay={0.3 + i * 0.15} />
              </span>
            </motion.div>
          );
        })}
      </div>

      <motion.div
        className="rp2-val-best"
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.6, duration: 0.4, ...SPRING }}
      >
        <span className="rp2-val-best-label">List at</span>
        <span className="rp2-val-best-price">
          <AnimatedPrice value={Math.round(bestValue * 0.95)} delay={0.7} />
        </span>
      </motion.div>
    </motion.div>
  );
}

// ── One item with its 3 agent feeds ──────────────────
function ItemResearchCard({ item, index, totalItems, v2Agents, screenshots, decision, onFocusAgent, onHeroPreview }) {
  const itemId = item?.item_id || '';
  const hasDamage = item.visible_defects?.length > 0;
  const heroSrc = item.hero_frame_paths?.[0];
  const heroOpen = Boolean(heroSrc && onHeroPreview);

  const allDone = useMemo(() => {
    return RESEARCH_PLATFORMS.every(p => {
      const agent = v2Agents?.[`${p}-research-${itemId}`];
      return agent?.status === STATUS_COMPLETE;
    });
  }, [v2Agents, itemId]);

  const researchValuation = useMemo(
    () => valuationFromResearchAgents(itemId, v2Agents),
    [itemId, v2Agents],
  );

  const valuationDecision = useMemo(
    () => mergeDecisionForValuation(decision, researchValuation),
    [decision, researchValuation],
  );

  const agentsFirst = index === 1;

  return (
    <motion.div
      className={`rp2-card${agentsFirst ? ' rp2-card-agents-first' : ''}`}
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, delay: index * 0.15, ease: EASE }}
    >
      <div
        className={`rp2-card-hero${heroOpen ? ' rp2-card-hero--clickable' : ''}`}
        role={heroOpen ? 'button' : undefined}
        tabIndex={heroOpen ? 0 : undefined}
        aria-label={heroOpen ? `Enlarge photo for ${item.name_guess}` : undefined}
        onClick={heroOpen ? () => onHeroPreview(heroSrc) : undefined}
        onKeyDown={
          heroOpen
            ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onHeroPreview(heroSrc);
                }
              }
            : undefined
        }
      >
        <div className="rp2-card-glow" />
        <div className="rp2-card-img">
          {heroSrc ? (
            <img src={heroSrc} alt={item.name_guess} />
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

      <div className="rp2-card-agents">
        {RESEARCH_PLATFORMS.map((platform) => (
          <AgentTile
            key={platform}
            platform={platform}
            agentId={`${platform}-research-${itemId}`}
            screenshots={screenshots}
            v2Agents={v2Agents}
            onClick={onFocusAgent}
          />
        ))}
      </div>

      <AnimatePresence>
        {allDone && valuationDecision && (
          <ValuationCard decision={valuationDecision} item={item} />
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Main page ────────────────────────────────────────
export default function ResearchPage({ items, bids, decisions, v2Agents, screenshots, send }) {
  const [focusedAgentId, setFocusedAgentId] = useState(null);
  const [heroPreviewUrl, setHeroPreviewUrl] = useState(null);

  const openAgentFocus = useCallback((agentId) => {
    setHeroPreviewUrl(null);
    setFocusedAgentId(agentId);
  }, []);

  const openHeroPreview = useCallback((url) => {
    setFocusedAgentId(null);
    setHeroPreviewUrl(url);
  }, []);

  useEffect(() => {
    if (!heroPreviewUrl) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') setHeroPreviewUrl(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [heroPreviewUrl]);

  if (!items || items.length === 0) return null;

  const singleItem = items.length === 1;
  const itemsLayoutN = Math.min(items.length, 3);
  const focusedShot = focusedAgentId ? getScreenshot(screenshots, focusedAgentId) : null;
  const focusedAgent = focusedAgentId ? resolveAgentForFocus(focusedAgentId, v2Agents) : null;

  return (
    <div
      className={`rp2-page rp2-page--items-${itemsLayoutN}${singleItem ? ' rp2-page--single' : ''}`}
    >
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
            onFocusAgent={openAgentFocus}
            onHeroPreview={openHeroPreview}
          />
        ))}
      </div>

      {heroPreviewUrl && (
        <div
          className={singleItem ? 'rp2-preview-overlay rp2-preview-overlay--single' : 'rp2-preview-overlay'}
          onClick={() => setHeroPreviewUrl(null)}
          role="presentation"
        >
          <button
            type="button"
            className="rp2-preview-close"
            onClick={() => setHeroPreviewUrl(null)}
            aria-label="Close preview"
          >
            ×
          </button>
          <img
            src={heroPreviewUrl}
            alt=""
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}

      <FocusMode
        agent={focusedAgent}
        screenshotUrl={focusedShot}
        onClose={() => setFocusedAgentId(null)}
        send={send}
        immersive
      />
    </div>
  );
}
