import { useState, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket, Globe, Monitor, Package, CheckCircle2,
  Loader2, XCircle, ExternalLink, ShoppingBag, RefreshCw,
  Wrench, RotateCcw, TrendingUp, ArrowLeft, Send, Sparkles,
} from 'lucide-react';
import Badge from '../shared/Badge';
import AnimatedValue from '../shared/AnimatedValue';

const E = [0.22, 1, 0.36, 1];

const PLATFORMS = [
  { id: 'ebay', domain: 'ebay.com/sell', seed: 'pw-ebay' },
  { id: 'facebook', domain: 'facebook.com/marketplace', seed: 'pw-fb' },
  { id: 'depop', domain: 'depop.com/create', seed: 'pw-depop' },
  { id: 'mercari', domain: 'mercari.com/sell', seed: 'pw-merc' },
];

const SLOT_CLASSES = ['pw-slot-tl', 'pw-slot-tr', 'pw-slot-bl', 'pw-slot-br'];

const ROUTE_LABELS = {
  sell_as_is: 'Resale',
  trade_in: 'Trade-In',
  repair_then_sell: 'Repair & Sell',
  return: 'Return',
  no_action: 'No Action',
};

const ROUTE_ICONS = {
  sell_as_is: ShoppingBag,
  trade_in: RefreshCw,
  repair_then_sell: Wrench,
  return: RotateCcw,
};

const ROUTE_GLOW = {
  sell_as_is: 'rgba(255, 160, 100, 0.10)',
  trade_in: 'rgba(142, 188, 255, 0.10)',
  repair_then_sell: 'rgba(255, 196, 136, 0.10)',
  return: 'rgba(200, 160, 255, 0.10)',
};

const MOCK_VIEW_SRC = (seed) =>
  `https://picsum.photos/seed/${seed}/200/310`;

const STATUS_CONFIG = {
  in_progress: { icon: Loader2, label: 'Posting...', cls: 'pw-status-posting', spin: true },
  success: { icon: CheckCircle2, label: 'Posted', cls: 'pw-status-done' },
  failed: { icon: XCircle, label: 'Failed', cls: 'pw-status-failed' },
};

/* ── Phase 1: Decision card ────────────────────────────── */

function ItemDecisionCard({ item, decision, index, isPosted, onPost }) {
  const value = decision?.estimated_best_value ?? 0;
  const routeKey = decision?.best_route;
  const routeLabel = routeKey ? ROUTE_LABELS[routeKey] || routeKey : '—';
  const RouteIcon = ROUTE_ICONS[routeKey] || TrendingUp;
  const img = item?.hero_frame_paths?.[0];
  const title = item?.name_guess || 'Unknown Item';
  const glowColor = ROUTE_GLOW[routeKey] || 'rgba(255, 180, 160, 0.08)';

  const routes = useMemo(() => {
    if (!decision?.alternatives) return [];
    const seen = new Set();
    return [decision.winning_bid, ...decision.alternatives]
      .filter(Boolean)
      .filter((r) => { if (seen.has(r.route_type)) return false; seen.add(r.route_type); return true; })
      .filter((r) => r.viable !== false)
      .slice(0, 3);
  }, [decision]);

  const d = index * 0.14;

  return (
    <motion.div
      className={`pw-decision-card ${isPosted ? 'pw-dc-posted' : ''}`}
      style={{ '--card-glow': glowColor }}
      initial={{ opacity: 0, y: 40, scale: 0.92, filter: 'blur(8px)' }}
      animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
      transition={{ delay: d + 0.08, duration: 0.7, ease: E }}
      whileHover={{
        y: -6,
        transition: { duration: 0.35, ease: E },
      }}
    >
      {/* Noise texture overlay */}
      <div className="pw-card-noise" />

      <motion.span className="pw-dc-name"
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: d + 0.2, duration: 0.5, ease: E }}
      >{title}</motion.span>

      <motion.div className="pw-dc-image-wrap"
        initial={{ opacity: 0, scale: 0.94 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: d + 0.16, duration: 0.6, ease: E }}
      >
        {img ? (
          <img src={img} alt={title} className="pw-dc-thumb" />
        ) : (
          <div className="pw-dc-thumb-empty">
            <Package size={32} strokeWidth={1.2} />
          </div>
        )}
        <AnimatePresence>
          {isPosted && (
            <motion.div className="pw-dc-posted-badge"
              initial={{ opacity: 0, scale: 0.7, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.7 }}
              transition={{ type: 'spring', damping: 16, stiffness: 300 }}
            >
              <CheckCircle2 size={14} />
              <span>Queued</span>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      <div className="pw-dc-info">
        <motion.div className="pw-dc-value"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: d + 0.3, duration: 0.5, ease: E }}
        >
          <RouteIcon size={16} />
          <AnimatedValue value={value} prefix="$" decimals={2} positive />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: d + 0.36, type: 'spring', damping: 16, stiffness: 280 }}
        >
          <Badge variant="success">{routeLabel}</Badge>
        </motion.div>
      </div>

      {decision?.route_reason && (
        <motion.div className="pw-dc-reason"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: d + 0.42, duration: 0.5, ease: E }}
        >{decision.route_reason}</motion.div>
      )}

      {routes.length > 0 && (
        <motion.div className="pw-dc-routes"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: d + 0.48, duration: 0.45, ease: E }}
        >
          {routes.map((route, ri) => {
            const Icon = ROUTE_ICONS[route.route_type] || TrendingUp;
            return (
              <div key={route.route_type} className={`pw-dc-route ${ri === 0 ? 'pw-dc-route-winner' : ''}`}>
                <Icon size={12} />
                <span>{ROUTE_LABELS[route.route_type] || route.route_type}</span>
                <span className="pw-dc-route-val">${route.estimated_value?.toFixed(0)}</span>
              </div>
            );
          })}
        </motion.div>
      )}

      <motion.button
        className={`pw-dc-post-btn ${isPosted ? 'pw-dc-post-btn-done' : ''}`}
        onClick={() => !isPosted && onPost(item.item_id)}
        disabled={isPosted}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: d + 0.54, duration: 0.45, ease: E }}
        whileHover={!isPosted ? { scale: 1.03, y: -1 } : {}}
        whileTap={!isPosted ? { scale: 0.96 } : {}}
      >
        <span style={{ position: 'relative', zIndex: 1, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {isPosted ? (
            <><CheckCircle2 size={14} /> Queued for posting</>
          ) : (
            <><Send size={14} /> Post this item</>
          )}
        </span>
      </motion.button>
    </motion.div>
  );
}

/* ── Phase 2: Browser mock ──────────────────────────────── */

function BrowserInstanceMock({ platform, seedSuffix, posIndex, clusterIndex, postStatus }) {
  const [imgOk, setImgOk] = useState(true);
  const seed = `${platform.seed}-${seedSuffix}`;
  const cfg = postStatus ? STATUS_CONFIG[postStatus.status] : null;

  return (
    <motion.div
      className={`pw-browser-slot ${SLOT_CLASSES[posIndex]} ${cfg?.cls || ''}`}
      initial={{ opacity: 0, scale: 0.7, y: 14, filter: 'blur(6px)' }}
      animate={{ opacity: 1, scale: 1, y: 0, filter: 'blur(0px)' }}
      transition={{
        delay: 0.3 + posIndex * 0.12 + clusterIndex * 0.18,
        type: 'spring',
        stiffness: 200,
        damping: 22,
      }}
      whileHover={{
        scale: 1.05,
        y: -3,
        transition: { duration: 0.25, ease: E },
      }}
    >
      <div className={`pw-browser-mock ${cfg?.cls || ''}`}>
        <div className="pw-browser-chrome">
          <div className="pw-browser-dots"><span /><span /><span /></div>
          <div className="pw-browser-url">
            <Globe size={9} className="pw-browser-url-icon" />
            <span>{platform.domain}</span>
          </div>
          {cfg && (
            <div className={`pw-chrome-status ${cfg.cls}`}>
              <cfg.icon size={10} className={cfg.spin ? 'mc-spinner' : ''} />
            </div>
          )}
        </div>
        <div className="pw-browser-body">
          {imgOk && (
            <img src={MOCK_VIEW_SRC(seed)} alt="" className="pw-browser-img" loading="lazy" onError={() => setImgOk(false)} />
          )}
          {!imgOk && (
            <div className="pw-browser-fallback pw-browser-fallback-visible">
              <Monitor size={22} strokeWidth={1.25} />
              <span>Agent viewport</span>
            </div>
          )}
          <div className="pw-browser-platform"><Badge platform={platform.id} /></div>
          <AnimatePresence>
            {cfg && (
              <motion.div
                className={`pw-browser-overlay ${cfg.cls}`}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.35, ease: E }}
              >
                <cfg.icon size={22} className={cfg.spin ? 'mc-spinner' : ''} />
                <span>{cfg.label}</span>
                {postStatus?.status === 'success' && postStatus.listing_url && (
                  <a href={postStatus.listing_url} target="_blank" rel="noopener noreferrer"
                    className="pw-listing-link" onClick={(e) => e.stopPropagation()}>
                    <ExternalLink size={11} /> View
                  </a>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}

function ItemPostingCluster({ item, decision, slotIndex, postingStatus = {} }) {
  const itemId = item?.item_id;
  const title = item?.name_guess || `Item ${slotIndex + 1}`;
  const img = item?.hero_frame_paths?.[0];
  const allDone = PLATFORMS.every((p) => postingStatus[`${itemId}:${p.id}`]?.status === 'success');
  const anyPosting = PLATFORMS.some((p) => postingStatus[`${itemId}:${p.id}`]?.status === 'in_progress');

  return (
    <motion.div
      className={`pw-item-cluster ${allDone ? 'pw-cluster-done' : ''} ${anyPosting ? 'pw-cluster-active' : ''}`}
      initial={{ opacity: 0, y: 30, filter: 'blur(8px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      exit={{ opacity: 0, scale: 0.95, filter: 'blur(6px)' }}
      transition={{ delay: 0.08 * slotIndex, duration: 0.6, ease: E }}
    >
      {PLATFORMS.map((p, i) => (
        <BrowserInstanceMock
          key={p.id}
          platform={p}
          seedSuffix={itemId || `slot-${slotIndex}`}
          posIndex={i}
          clusterIndex={slotIndex}
          postStatus={postingStatus[`${itemId}:${p.id}`]}
        />
      ))}

      <motion.div
        className="pw-item-core"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.2 + slotIndex * 0.1, type: 'spring', damping: 22, stiffness: 180 }}
      >
        <div className="pw-item-visual">
          {img ? (
            <img src={img} alt="" className="pw-item-img" />
          ) : (
            <div className="pw-item-placeholder"><Package size={28} strokeWidth={1.2} /></div>
          )}
        </div>
        <span className="pw-item-name">{title}</span>
      </motion.div>
    </motion.div>
  );
}

/* ── Main component ─────────────────────────────────────── */

export default function PostingWorkspace({ items = [], decisions = {}, postingStatus = {}, initialStarted = false }) {
  const [postedIds, setPostedIds] = useState(() => new Set());
  const [phase, setPhase] = useState(initialStarted ? 'browsers' : 'decisions');

  const displayItems = useMemo(() => {
    const list = (items || []).slice(0, 3);
    while (list.length < 3) {
      list.push({ item_id: `placeholder-${list.length}`, name_guess: `Item ${list.length + 1}` });
    }
    return list;
  }, [items]);

  const totalValue = useMemo(() => {
    return displayItems.reduce((sum, item) => {
      const d = decisions[item.item_id];
      return sum + (d?.estimated_best_value || 0);
    }, 0);
  }, [displayItems, decisions]);

  const postedItems = useMemo(
    () => displayItems.filter((item) => postedIds.has(item.item_id)),
    [displayItems, postedIds],
  );

  const postItem = useCallback((itemId) => {
    setPostedIds((prev) => new Set(prev).add(itemId));
  }, []);

  const postAll = useCallback(() => {
    setPostedIds(new Set(displayItems.map((i) => i.item_id)));
  }, [displayItems]);

  const goToBrowsers = useCallback(() => {
    if (postedIds.size > 0) setPhase('browsers');
  }, [postedIds]);

  const goBack = useCallback(() => {
    setPhase('decisions');
  }, []);

  const allPosted = postedIds.size === displayItems.length;

  return (
    <div className="pw-root mc-embedded">
      <AnimatePresence mode="wait">
        {phase === 'decisions' ? (
          <motion.div
            key="decisions"
            className="pw-decisions-phase"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -24, scale: 0.98, filter: 'blur(14px)' }}
            transition={{ duration: 0.5, ease: E }}
          >
            {totalValue > 0 && (
              <motion.div className="pw-total-banner"
                initial={{ opacity: 0, y: -14, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ delay: 0.08, duration: 0.5, ease: E }}
              >
                <Sparkles size={13} style={{ opacity: 0.45 }} />
                <span className="pw-total-label">Total Recovery Value</span>
                <AnimatedValue value={totalValue} prefix="$" decimals={2} large positive />
              </motion.div>
            )}

            <div className="pw-decisions-grid">
              {displayItems.map((item, i) => (
                <ItemDecisionCard
                  key={item.item_id}
                  item={item}
                  decision={decisions[item.item_id]}
                  index={i}
                  isPosted={postedIds.has(item.item_id)}
                  onPost={postItem}
                />
              ))}
            </div>

            <motion.div className="pw-post-actions"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4, duration: 0.6, ease: E }}
            >
              <AnimatePresence mode="wait">
                {!allPosted && (
                  <motion.button
                    key="post-all"
                    type="button"
                    className="pw-post-all-btn"
                    onClick={postAll}
                    initial={{ opacity: 0, scale: 0.92 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.9, filter: 'blur(4px)' }}
                    whileHover={{ scale: 1.04, y: -2 }}
                    whileTap={{ scale: 0.96 }}
                    transition={{ duration: 0.25, ease: E }}
                  >
                    <Sparkles size={15} />
                    Post all items
                  </motion.button>
                )}
              </AnimatePresence>

              <AnimatePresence>
                {postedIds.size > 0 && (
                  <motion.button
                    type="button"
                    className="pw-go-btn"
                    onClick={goToBrowsers}
                    initial={{ opacity: 0, scale: 0.85, y: 8 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.85, y: 8 }}
                    whileHover={{ scale: 1.04, y: -2 }}
                    whileTap={{ scale: 0.96 }}
                    transition={{ type: 'spring', damping: 18, stiffness: 260 }}
                  >
                    Start posting {postedIds.size} item{postedIds.size !== 1 ? 's' : ''}
                    <Rocket size={14} />
                  </motion.button>
                )}
              </AnimatePresence>
            </motion.div>
          </motion.div>
        ) : (
          <motion.div
            key="browsers"
            className="pw-live"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97, filter: 'blur(10px)' }}
            transition={{ duration: 0.6, ease: E }}
          >
            <div className="pw-live-header">
              <motion.button
                className="pw-back-btn"
                onClick={goBack}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.1, duration: 0.3, ease: E }}
                whileHover={{ x: -2 }}
                whileTap={{ scale: 0.96 }}
              >
                <ArrowLeft size={14} />
                Back to items
              </motion.button>
              <motion.span className="pw-live-count"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.2, duration: 0.3, ease: E }}
              >
                Posting {postedItems.length} item{postedItems.length !== 1 ? 's' : ''} to {PLATFORMS.length} platforms
              </motion.span>
            </div>

            <div className={`pw-grid pw-grid-${postedItems.length}`}>
              <AnimatePresence>
                {postedItems.map((item, i) => (
                  <ItemPostingCluster
                    key={item.item_id}
                    item={item}
                    decision={decisions[item.item_id]}
                    slotIndex={i}
                    postingStatus={postingStatus}
                  />
                ))}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
