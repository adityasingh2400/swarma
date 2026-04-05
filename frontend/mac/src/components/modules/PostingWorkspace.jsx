import { useState, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket, Globe, Monitor, Package, CheckCircle2,
  Loader2, XCircle, ExternalLink, ShoppingBag, RefreshCw,
  Wrench, RotateCcw, TrendingUp, ArrowLeft, Send, Sparkles,
  ChevronLeft, ChevronRight,
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

const CORNER_CLASSES = ['pw-corner-tl', 'pw-corner-tr', 'pw-corner-bl', 'pw-corner-br'];

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

function ItemDecisionCard({ item, decision, index, onPost }) {
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
      className="pw-decision-card"
      style={{ '--card-glow': glowColor }}
      initial={{ opacity: 0, y: 40, scale: 0.92, filter: 'blur(8px)' }}
      animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
      transition={{ delay: d + 0.08, duration: 0.7, ease: E }}
      whileHover={{ y: -6, transition: { duration: 0.35, ease: E } }}
    >
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
        className="pw-dc-post-btn"
        onClick={() => onPost(item.item_id)}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: d + 0.54, duration: 0.45, ease: E }}
        whileHover={{ scale: 1.03, y: -1 }}
        whileTap={{ scale: 0.96 }}
      >
        <span style={{ position: 'relative', zIndex: 1, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <Send size={14} /> Post this item
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
      className={`pw-corner-browser ${CORNER_CLASSES[posIndex]} ${cfg?.cls || ''}`}
      initial={{ opacity: 0, scale: 0.7, filter: 'blur(6px)' }}
      animate={{ opacity: 1, scale: 1, filter: 'blur(0px)' }}
      transition={{
        delay: 0.25 + posIndex * 0.1 + clusterIndex * 0.15,
        type: 'spring',
        stiffness: 200,
        damping: 22,
      }}
      whileHover={{ scale: 1.04, transition: { duration: 0.25, ease: E } }}
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

function FullPageCluster({ item, decision, slotIndex, postingStatus = {} }) {
  const itemId = item?.item_id;
  const title = item?.name_guess || `Item ${slotIndex + 1}`;
  const img = item?.hero_frame_paths?.[0];
  const allDone = PLATFORMS.every((p) => postingStatus[`${itemId}:${p.id}`]?.status === 'success');
  const anyPosting = PLATFORMS.some((p) => postingStatus[`${itemId}:${p.id}`]?.status === 'in_progress');

  return (
    <div className={`pw-fullpage-cluster ${allDone ? 'pw-cluster-done' : ''} ${anyPosting ? 'pw-cluster-active' : ''}`}>
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
        className="pw-center-item"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.15, type: 'spring', damping: 22, stiffness: 180 }}
      >
        <div className="pw-center-visual">
          {img ? (
            <img src={img} alt="" className="pw-center-img" />
          ) : (
            <div className="pw-center-placeholder"><Package size={36} strokeWidth={1.2} /></div>
          )}
        </div>
        <span className="pw-center-name">{title}</span>
        {decision?.estimated_best_value > 0 && (
          <span className="pw-center-value">
            <AnimatedValue value={decision.estimated_best_value} prefix="$" decimals={2} positive />
          </span>
        )}
      </motion.div>
    </div>
  );
}

/* ── Carousel slide animation variants ── */
const slideVariants = {
  enter: (dir) => ({ x: dir > 0 ? 300 : -300, opacity: 0, scale: 0.95 }),
  center: { x: 0, opacity: 1, scale: 1 },
  exit: (dir) => ({ x: dir > 0 ? -300 : 300, opacity: 0, scale: 0.95 }),
};

/* ── Main component ─────────────────────────────────────── */

export default function PostingWorkspace({ items = [], decisions = {}, postingStatus = {}, initialStarted = false }) {
  const [postedIds, setPostedIds] = useState(() => new Set());
  const [phase, setPhase] = useState(initialStarted ? 'browsers' : 'decisions');
  const [carouselIdx, setCarouselIdx] = useState(0);
  const [slideDir, setSlideDir] = useState(1);

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

  const postSingle = useCallback((itemId) => {
    setPostedIds(new Set([itemId]));
    setCarouselIdx(0);
    setPhase('browsers');
  }, []);

  const postAll = useCallback(() => {
    setPostedIds(new Set(displayItems.map((i) => i.item_id)));
    setCarouselIdx(0);
    setPhase('browsers');
  }, [displayItems]);

  const goBack = useCallback(() => {
    setPostedIds(new Set());
    setPhase('decisions');
  }, []);

  const goPrev = useCallback(() => {
    setSlideDir(-1);
    setCarouselIdx((i) => Math.max(0, i - 1));
  }, []);

  const goNext = useCallback(() => {
    setSlideDir(1);
    setCarouselIdx((i) => Math.min(postedItems.length - 1, i + 1));
  }, [postedItems.length]);

  const isSolo = postedItems.length === 1;
  const isCarousel = postedItems.length > 1;

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
                  onPost={postSingle}
                />
              ))}
            </div>

            <motion.div className="pw-post-actions"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4, duration: 0.6, ease: E }}
            >
              <motion.button
                type="button"
                className="pw-post-all-btn"
                onClick={postAll}
                whileHover={{ scale: 1.04, y: -2 }}
                whileTap={{ scale: 0.96 }}
                transition={{ duration: 0.25, ease: E }}
              >
                <Sparkles size={15} />
                Post all items
              </motion.button>
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

              {isCarousel && (
                <div className="pw-carousel-dots">
                  {postedItems.map((_, i) => (
                    <button
                      key={i}
                      className={`pw-dot ${i === carouselIdx ? 'pw-dot-active' : ''}`}
                      onClick={() => { setSlideDir(i > carouselIdx ? 1 : -1); setCarouselIdx(i); }}
                    />
                  ))}
                </div>
              )}
            </div>

            <div className="pw-stage-area">
              {isCarousel && carouselIdx > 0 && (
                <motion.button
                  className="pw-carousel-arrow pw-arrow-left"
                  onClick={goPrev}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                >
                  <ChevronLeft size={20} />
                </motion.button>
              )}

              <AnimatePresence mode="wait" custom={slideDir}>
                <motion.div
                  key={postedItems[carouselIdx]?.item_id}
                  className="pw-stage-slide"
                  custom={slideDir}
                  variants={slideVariants}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ duration: 0.45, ease: E }}
                >
                  <FullPageCluster
                    item={postedItems[carouselIdx]}
                    decision={decisions[postedItems[carouselIdx]?.item_id]}
                    slotIndex={carouselIdx}
                    postingStatus={postingStatus}
                  />
                </motion.div>
              </AnimatePresence>

              {isCarousel && carouselIdx < postedItems.length - 1 && (
                <motion.button
                  className="pw-carousel-arrow pw-arrow-right"
                  onClick={goNext}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                >
                  <ChevronRight size={20} />
                </motion.button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
