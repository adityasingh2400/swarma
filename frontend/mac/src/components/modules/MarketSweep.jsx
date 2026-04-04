import { useState, useRef, useMemo, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BarChart3, ShoppingBag, RefreshCw, Wrench, Layers, Package,
  ExternalLink, Truck, ChevronLeft, ChevronRight, Trophy,
  Clock, Zap, Star, Sparkles, TrendingUp,
} from 'lucide-react';
import Badge from '../shared/Badge';

const LANE_CONFIG = {
  resale: {
    label: 'Resale',
    desc: 'Scanning comparable listings',
    color: '#7A1B2D',
    icon: ShoppingBag,
  },
  trade_in: {
    label: 'Trade-In',
    desc: 'Checking guaranteed payout options',
    color: '#4A7A2E',
    icon: RefreshCw,
  },
  repair: {
    label: 'Repair',
    desc: 'Searching replacement parts and ROI',
    color: '#9A7020',
    icon: Wrench,
  },
  bundle: {
    label: 'Bundle',
    desc: 'Testing grouped selling value',
    color: '#6B4A3A',
    icon: Layers,
  },
};

const PLATFORM_COLORS = {
  ebay: '#7A1B2D', mercari: '#7A1B2D', swappa: '#7A1B2D',
  amazon: '#7A1B2D', facebook: '#7A1B2D', offerup: '#7A1B2D',
  poshmark: '#7A1B2D', craigslist: '#7A1B2D', other: '#7A1B2D',
};

const ROUTE_LABELS = {
  sell_as_is: 'Sell As-Is', trade_in: 'Trade-In',
  repair_then_sell: 'Repair → Sell', bundle_then_sell: 'Bundle',
  return: 'Return',
};

function SkeletonCard() {
  return (
    <div className="sw-card sw-card-skeleton">
      <div className="sw-card-img sw-shimmer" />
      <div className="sw-card-body">
        <div className="sw-skel-line sw-shimmer" style={{ width: '80%' }} />
        <div className="sw-skel-line sw-shimmer" style={{ width: '40%', height: 20 }} />
        <div className="sw-skel-line sw-shimmer" style={{ width: '60%' }} />
      </div>
    </div>
  );
}

function ListingImage({ src, alt, platformColor }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const hasUrl = src && (src.startsWith('http') || src.startsWith('/'));

  if (!hasUrl || failed) {
    return (
      <div className="sw-card-img sw-card-img-fallback" style={{ background: `linear-gradient(135deg, ${platformColor}18, ${platformColor}08)` }}>
        <Package size={30} style={{ opacity: 0.4, color: platformColor }} />
      </div>
    );
  }

  return (
    <div className="sw-card-img">
      {!loaded && <div className="sw-card-img-placeholder sw-shimmer" />}
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
        style={{ opacity: loaded ? 1 : 0, transition: 'opacity 0.5s ease' }}
      />
    </div>
  );
}

function ResaleCard({ comp, index, isBest }) {
  const platformColor = PLATFORM_COLORS[comp.platform] || PLATFORM_COLORS.other;
  const hasUrl = comp.url && comp.url.startsWith('http');

  return (
    <motion.div
      className={`sw-card ${isBest ? 'sw-card-best' : ''}`}
      initial={{ opacity: 0, x: 80, scale: 0.88 }}
      animate={{ opacity: 1, x: 0, scale: isBest ? 1.03 : 1 }}
      transition={{ delay: index * 0.25, type: 'spring', stiffness: 120, damping: 16 }}
    >
      <ListingImage src={comp.image_url} alt={comp.title} platformColor={platformColor} />
      <div className="sw-card-badges">
        <Badge platform={comp.platform} />
        {comp.match_score != null && (
          <Badge variant={comp.match_score >= 90 ? 'success' : comp.match_score >= 80 ? 'primary' : 'neutral'}>
            {Math.round(comp.match_score)}%
          </Badge>
        )}
      </div>
      <div className="sw-card-body">
        <div className="sw-card-title">{comp.title}</div>
        <div className="sw-card-price-row">
          <span className="sw-card-price">${comp.price?.toFixed(2)}</span>
          {comp.shipping && (
            <span className="sw-card-shipping">
              <Truck size={9} /> {comp.shipping}
            </span>
          )}
        </div>
        <div className="sw-card-meta">
          <span className="sw-card-condition">{comp.condition}</span>
          {hasUrl && (
            <a href={comp.url} target="_blank" rel="noopener noreferrer" className="sw-card-link" onClick={(e) => e.stopPropagation()}>
              <ExternalLink size={9} /> View
            </a>
          )}
        </div>
        {isBest && (
          <div className="sw-card-tag sw-tag-best">
            <Star size={9} /> Best Match
          </div>
        )}
      </div>
    </motion.div>
  );
}

function QuoteCard({ quote, index, isBest }) {
  const SPEED = { instant: 'Instant', days: '2–3 days', week: '~1 week', weeks: '2–3 weeks', month_plus: '1+ month' };
  return (
    <motion.div
      className={`sw-card sw-quote-card ${isBest ? 'sw-card-best' : ''}`}
      initial={{ opacity: 0, x: 60 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.1, type: 'spring', stiffness: 160, damping: 18 }}
    >
      <div className="sw-quote-header" style={{ borderColor: isBest ? '#4A7A2E' : 'var(--border)' }}>
        <div className="sw-quote-provider">{quote.provider}</div>
        <div className="sw-quote-payout" style={{ color: isBest ? 'var(--success)' : 'var(--text-primary)' }}>
          ${quote.payout?.toFixed?.(2) ?? quote.payout}
        </div>
      </div>
      <div className="sw-card-body">
        <div className="sw-quote-details">
          <span><Clock size={10} /> {SPEED[quote.speed] || quote.speed}</span>
          <span><Zap size={10} /> {quote.effort} effort</span>
        </div>
        <div className="sw-quote-conf">
          <div className="sw-conf-bar">
            <div className="sw-conf-fill" style={{ width: `${(quote.confidence || 0) * 100}%` }} />
          </div>
          <span>{Math.round((quote.confidence || 0) * 100)}% confidence</span>
        </div>
        {isBest && <div className="sw-card-tag sw-tag-best"><Trophy size={9} /> Best Payout</div>}
      </div>
    </motion.div>
  );
}

function RepairCard({ part, index }) {
  return (
    <motion.div
      className="sw-card sw-repair-card"
      initial={{ opacity: 0, x: 60 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.1, type: 'spring', stiffness: 160, damping: 18 }}
    >
      <div className="sw-card-img sw-card-img-fallback" style={{ background: 'linear-gradient(135deg, #F5EDD8, #F0E5D0)' }}>
        {part.part_image_url ? (
          <img src={part.part_image_url} alt={part.part_name} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        ) : (
          <Wrench size={28} style={{ opacity: 0.4, color: '#9A7020' }} />
        )}
      </div>
      <div className="sw-card-body">
        <div className="sw-card-title">{part.part_name}</div>
        <div className="sw-card-price-row">
          <span className="sw-card-price" style={{ color: '#9A7020' }}>${part.part_price?.toFixed(2)}</span>
        </div>
        <div className="sw-card-meta">
          <Badge platform={part.source?.toLowerCase() || 'amazon'} />
        </div>
      </div>
    </motion.div>
  );
}

function SweepLane({ laneKey, config, data, isScanning, scanCount }) {
  const railRef = useRef(null);
  const Icon = config.icon;
  const isDone = !isScanning && data.length > 0;

  const scroll = useCallback((dir) => {
    railRef.current?.scrollBy({ left: dir * 260, behavior: 'smooth' });
  }, []);

  return (
    <div className="sw-lane">
      <div className="sw-lane-header">
        <div className="sw-lane-indicator" style={{ background: isScanning ? config.color : isDone ? 'var(--success)' : 'var(--border)' }}>
          {isScanning && <span className="sw-lane-pulse" style={{ background: config.color }} />}
        </div>
        <div className="sw-lane-info">
          <div className="sw-lane-label">
            <Icon size={14} style={{ color: config.color }} />
            <span>{config.label}</span>
            {isScanning && <span className="sw-lane-live" style={{ background: `${config.color}22`, color: config.color }}>scanning</span>}
            {isDone && <span className="sw-lane-live" style={{ background: 'var(--success-dim)', color: 'var(--success)' }}>done</span>}
          </div>
          <div className="sw-lane-desc">
            {isScanning ? config.desc : `${data.length} results found`}
            {scanCount > 0 && !isDone && <span style={{ color: config.color, marginLeft: 6 }}>({scanCount} scanned)</span>}
          </div>
        </div>
        {data.length > 3 && (
          <div className="sw-lane-nav">
            <button onClick={() => scroll(-1)}><ChevronLeft size={14} /></button>
            <button onClick={() => scroll(1)}><ChevronRight size={14} /></button>
          </div>
        )}
      </div>

      <div className="sw-lane-rail" ref={railRef}>
        {isScanning && data.length === 0 && (
          <>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </>
        )}

        <AnimatePresence>
          {laneKey === 'resale' && data.map((comp, i) => (
            <ResaleCard key={`${comp.platform}-${i}`} comp={comp} index={i} isBest={i === 0} />
          ))}
          {laneKey === 'trade_in' && data.map((quote, i) => (
            <QuoteCard key={quote.provider || i} quote={quote} index={i} isBest={i === 0} />
          ))}
          {laneKey === 'repair' && data.map((part, i) => (
            <RepairCard key={part.part_name || i} part={part} index={i} />
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

function RepairPayoff({ repairBid }) {
  if (!repairBid) return null;
  const asIs = repairBid.as_is_value || 0;
  const cost = repairBid.repair_cost || 0;
  const postRepair = repairBid.post_repair_value || 0;
  const netGain = repairBid.net_gain_unlocked || 0;

  return (
    <motion.div
      className="sw-repair-payoff"
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: 0.3 }}
    >
      <div className="sw-payoff-row">
        <span>Sell as-is</span>
        <span style={{ color: 'var(--text-secondary)' }}>${asIs.toFixed(0)}</span>
      </div>
      <div className="sw-payoff-row">
        <span>Repair cost</span>
        <span style={{ color: 'var(--danger)' }}>-${cost.toFixed(2)}</span>
      </div>
      <div className="sw-payoff-row">
        <span>After repair</span>
        <span style={{ color: 'var(--text-primary)' }}>${postRepair.toFixed(0)}</span>
      </div>
      {netGain > 0 && (
        <div className="sw-payoff-gain">
          <Sparkles size={12} />
          <span>+${netGain.toFixed(0)} unlocked</span>
        </div>
      )}
    </motion.div>
  );
}

function DecisionStrip({ itemBids, decision }) {
  const routes = useMemo(() => {
    if (!itemBids || itemBids.length === 0) return [];
    return itemBids
      .filter((b) => b.viable)
      .sort((a, b) => (b.estimated_value || 0) - (a.estimated_value || 0));
  }, [itemBids]);

  const winnerType = decision?.best_route;

  if (routes.length === 0) return null;

  return (
    <motion.div
      className="sw-decision-strip"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
    >
      <div className="sw-strip-routes">
        {routes.map((bid) => {
          const isWinner = bid.route_type === winnerType;
          return (
            <motion.div
              key={bid.route_type}
              className={`sw-strip-route ${isWinner ? 'sw-strip-winner' : ''}`}
              layout
            >
              <div className="sw-strip-label">{ROUTE_LABELS[bid.route_type] || bid.route_type}</div>
              <div className="sw-strip-value" style={{ color: isWinner ? 'var(--success)' : 'var(--text-primary)' }}>
                ${(bid.estimated_value || 0).toFixed(0)}
              </div>
              <div className="sw-strip-conf">
                {bid.speed === 'instant' || bid.speed === 'days' ? 'fast' : bid.speed}
              </div>
            </motion.div>
          );
        })}
      </div>
      {winnerType && (
        <motion.div
          className="sw-strip-best"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.5, type: 'spring' }}
        >
          <Trophy size={14} />
          <span>Best route: <strong>{ROUTE_LABELS[winnerType] || winnerType}</strong></span>
        </motion.div>
      )}
    </motion.div>
  );
}

export default function MarketSweep({ job, items, bids, decisions }) {
  const [selectedItemId, setSelectedItemId] = useState(null);

  useEffect(() => {
    if (items.length > 0 && !selectedItemId) {
      setSelectedItemId(items[0].item_id);
    }
  }, [items, selectedItemId]);

  const selectedItem = useMemo(() => items.find((i) => i.item_id === selectedItemId), [items, selectedItemId]);
  const itemBids = useMemo(() => (bids || {})[selectedItemId] || [], [bids, selectedItemId]);
  const itemDecision = useMemo(() => (decisions || {})[selectedItemId], [decisions, selectedItemId]);

  const isRouting = job?.status === 'routing';

  const laneData = useMemo(() => {
    const sellBid = itemBids.find((b) => b.route_type === 'sell_as_is');
    const tradeBid = itemBids.find((b) => b.route_type === 'trade_in');
    const repairBid = itemBids.find((b) => b.route_type === 'repair_then_sell');
    const bundleBid = itemBids.find((b) => b.route_type === 'bundle_then_sell');

    const resaleComps = sellBid?.comparable_listings || [];
    const tradeQuotes = tradeBid?.trade_in_quotes || [];
    const repairParts = repairBid?.repair_candidates || [];

    const isElectronics = selectedItem?.category === 'electronics';
    const hasDefects = (selectedItem?.visible_defects?.length || 0) + (selectedItem?.spoken_defects?.length || 0) > 0;

    return {
      resale: { data: resaleComps.sort((a, b) => (b.match_score || 0) - (a.match_score || 0)), bid: sellBid },
      trade_in: { data: tradeQuotes.sort((a, b) => (b.payout || 0) - (a.payout || 0)), bid: tradeBid, show: isElectronics },
      repair: { data: repairParts, bid: repairBid, show: hasDefects },
      bundle: { data: [], bid: bundleBid, show: items.length > 1 },
    };
  }, [itemBids, selectedItem, items]);

  const statusText = useMemo(() => {
    if (!selectedItem) return 'Select an item';
    if (isRouting) {
      const done = itemBids.length;
      if (done === 0) return 'Scanning resale comps…';
      return `Comparing routes… (${done} found)`;
    }
    if (itemDecision) return 'Analysis complete';
    if (itemBids.length > 0) return `${itemBids.length} routes evaluated`;
    return 'Waiting for analysis…';
  }, [selectedItem, isRouting, itemBids, itemDecision]);

  if (items.length === 0) {
    return (
      <div className="empty-state">
        <BarChart3 size={32} className="empty-state-icon" />
        <p className="empty-state-text">Upload a video to start market analysis</p>
      </div>
    );
  }

  return (
    <div className="sweep-theater">
      {/* ── Header ── */}
      <div className="sw-header">
        <div className="sw-header-left">
          <TrendingUp size={16} style={{ color: 'var(--primary)' }} />
          <span className="sw-header-title">Market Sweep</span>
          {(isRouting || (selectedItem && !itemDecision)) && (
            <span className="sw-header-pulse" />
          )}
        </div>
        <div className="sw-header-status">{statusText}</div>
        <div className="sw-item-selector">
          {items.map((item) => (
            <button
              key={item.item_id}
              className={`sw-item-btn ${item.item_id === selectedItemId ? 'active' : ''}`}
              onClick={() => setSelectedItemId(item.item_id)}
            >
              <div className="sw-item-thumb">
                {item.hero_frame_paths?.[0] ? (
                  <img src={item.hero_frame_paths[0]} alt="" />
                ) : (
                  <Package size={12} />
                )}
              </div>
              <span>{item.name_guess}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Lanes ── */}
      <div className="sw-lanes">
        <SweepLane
          laneKey="resale"
          config={LANE_CONFIG.resale}
          data={laneData.resale.data}
          isScanning={isRouting && !laneData.resale.bid}
          scanCount={laneData.resale.data.length}
        />

        {(laneData.trade_in.show || laneData.trade_in.bid) && (
          <SweepLane
            laneKey="trade_in"
            config={LANE_CONFIG.trade_in}
            data={laneData.trade_in.data}
            isScanning={isRouting && !laneData.trade_in.bid}
            scanCount={laneData.trade_in.data.length}
          />
        )}

        {(laneData.repair.show || laneData.repair.bid) && (
          <>
            <SweepLane
              laneKey="repair"
              config={LANE_CONFIG.repair}
              data={laneData.repair.data}
              isScanning={isRouting && !laneData.repair.bid}
              scanCount={laneData.repair.data.length}
            />
            <RepairPayoff repairBid={laneData.repair.bid} />
          </>
        )}

        {(laneData.bundle.show || laneData.bundle.bid) && (
          <SweepLane
            laneKey="bundle"
            config={LANE_CONFIG.bundle}
            data={laneData.bundle.data}
            isScanning={isRouting && !laneData.bundle.bid}
            scanCount={0}
          />
        )}
      </div>

      {/* ── Decision Strip ── */}
      <DecisionStrip itemBids={itemBids} decision={itemDecision} />
    </div>
  );
}
