import { useMemo, useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Zap, TrendingUp, ShoppingBag, RefreshCw, Wrench, RotateCcw,
  Trophy, X, Package, Shield, Star, ArrowUpRight,
} from 'lucide-react';
import AnimatedValue from '../shared/AnimatedValue';
import Badge from '../shared/Badge';
import CircularCarousel from '../shared/CircularCarousel';

const ROUTE_ICONS = {
  sell_as_is: ShoppingBag,
  trade_in: RefreshCw,
  repair_then_sell: Wrench,
  return: RotateCcw,
};

const ROUTE_LABELS = {
  sell_as_is: 'Sell As-Is',
  trade_in: 'Trade-In',
  repair_then_sell: 'Repair & Sell',
  return: 'Return',
};

const BUBBLE_EASE = [0.16, 1, 0.3, 1];

function ItemDetailExpanded({ item, decision, onClose, onExecuteItem }) {
  const Icon = ROUTE_ICONS[decision.best_route] || TrendingUp;
  const hasDamage = item.visible_defects?.length > 0;
  const condition = hasDamage ? 'Good — Minor wear' : 'Excellent';

  const routes = useMemo(() => {
    if (!decision?.alternatives) return [];
    const seen = new Set();
    return [decision.winning_bid, ...decision.alternatives]
      .filter(Boolean)
      .filter((r) => { if (seen.has(r.route_type)) return false; seen.add(r.route_type); return true; })
      .filter((r) => r.viable !== false)
      .slice(0, 4);
  }, [decision]);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <motion.div
      className="ide-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: BUBBLE_EASE }}
      onClick={onClose}
    >
      <motion.button
        className="ide-close"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.2, duration: 0.3, ease: BUBBLE_EASE }}
        onClick={onClose}
      >
        <X size={18} />
      </motion.button>

      <div className="ide-canvas" onClick={(e) => e.stopPropagation()}>
        {/* Center hero */}
        <motion.div
          className="ide-hero"
          initial={{ scale: 0.7, opacity: 0, y: 30 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: BUBBLE_EASE }}
        >
          <div className="ide-hero-glow" />
          <div className="ide-hero-img-wrap">
            {item.hero_frame_paths?.[0] ? (
              <img src={item.hero_frame_paths[0]} alt={item.name_guess} className="ide-hero-img" />
            ) : (
              <div className="ide-hero-placeholder"><Package size={48} /></div>
            )}
          </div>
          <h2 className="ide-hero-name">{item.name_guess}</h2>
          <motion.div
            className="ide-hero-price"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.4, ease: BUBBLE_EASE }}
          >
            <Icon size={22} />
            <AnimatedValue value={decision.estimated_best_value || 0} prefix="$" decimals={2} positive />
          </motion.div>
        </motion.div>

        {/* Left floating bubbles */}
        <div className="ide-bubbles ide-bubbles-left">
          <motion.div
            className="ide-bubble"
            initial={{ opacity: 0, x: -60, scale: 0.85 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            transition={{ delay: 0.15, duration: 0.5, ease: BUBBLE_EASE }}
          >
            <div className="ide-bubble-icon ide-bubble-route"><Icon size={16} /></div>
            <div className="ide-bubble-label">Best Route</div>
            <div className="ide-bubble-value">{ROUTE_LABELS[decision.best_route] || decision.best_route}</div>
          </motion.div>

          <motion.div
            className="ide-bubble"
            initial={{ opacity: 0, x: -60, scale: 0.85 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            transition={{ delay: 0.25, duration: 0.5, ease: BUBBLE_EASE }}
          >
            <div className="ide-bubble-icon ide-bubble-condition"><Shield size={16} /></div>
            <div className="ide-bubble-label">Condition</div>
            <div className="ide-bubble-value">{condition}</div>
          </motion.div>

          <motion.div
            className="ide-bubble"
            initial={{ opacity: 0, x: -60, scale: 0.85 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            transition={{ delay: 0.35, duration: 0.5, ease: BUBBLE_EASE }}
          >
            <div className="ide-bubble-icon ide-bubble-confidence"><Star size={16} /></div>
            <div className="ide-bubble-label">Confidence</div>
            <div className="ide-bubble-value">{Math.round((decision.winning_bid?.confidence || 0.85) * 100)}%</div>
          </motion.div>
        </div>

        {/* Right floating bubbles */}
        <div className="ide-bubbles ide-bubbles-right">
          {routes.map((route, i) => {
            const RouteIcon = ROUTE_ICONS[route.route_type] || TrendingUp;
            const isWinner = i === 0;
            return (
              <motion.div
                key={route.route_type}
                className={`ide-bubble ide-bubble-route-alt ${isWinner ? 'ide-bubble-winner' : ''}`}
                initial={{ opacity: 0, x: 60, scale: 0.85 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                transition={{ delay: 0.15 + i * 0.1, duration: 0.5, ease: BUBBLE_EASE }}
              >
                <div className="ide-bubble-icon"><RouteIcon size={16} /></div>
                <div className="ide-bubble-label">{ROUTE_LABELS[route.route_type] || route.route_type}</div>
                <div className="ide-bubble-value">${route.estimated_value?.toFixed(0)}</div>
                {isWinner && <div className="ide-bubble-tag">Best</div>}
              </motion.div>
            );
          })}
        </div>

        {/* Bottom: reason + execute */}
        <motion.div
          className="ide-bottom"
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, duration: 0.5, ease: BUBBLE_EASE }}
        >
          {decision.route_reason && (
            <p className="ide-reason">{decision.route_reason}</p>
          )}
          <button
            className="ide-execute"
            onClick={() => {
              onExecuteItem(item.item_id, ['facebook']);
              onClose();
            }}
          >
            <Zap size={16} />
            Execute Route
            <ArrowUpRight size={14} />
          </button>
        </motion.div>
      </div>
    </motion.div>
  );
}

function DecisionCard({ item, decision, onExecuteItem, onExpand }) {
  const Icon = ROUTE_ICONS[decision.best_route] || TrendingUp;

  const routes = useMemo(() => {
    if (!decision?.alternatives) return [];
    const seen = new Set();
    return [decision.winning_bid, ...decision.alternatives]
      .filter(Boolean)
      .filter((r) => { if (seen.has(r.route_type)) return false; seen.add(r.route_type); return true; })
      .filter((r) => r.viable !== false)
      .slice(0, 3);
  }, [decision]);

  return (
    <div className="decision-carousel-inner" onClick={() => onExpand?.(item)}>
      <div className="decision-fs-card-header">
        {item.hero_frame_paths?.[0] && (
          <img src={item.hero_frame_paths[0]} alt={item.name_guess} className="decision-fs-card-thumb" />
        )}
        <div className="decision-fs-card-info">
          <span className="decision-fs-card-name">{item.name_guess}</span>
          <Badge variant="success">
            {ROUTE_LABELS[decision.best_route] || decision.best_route}
          </Badge>
        </div>
      </div>

      <div className="decision-fs-card-value">
        <Icon size={20} />
        <AnimatedValue value={decision.estimated_best_value || 0} prefix="$" decimals={2} positive />
      </div>

      {decision.route_reason && (
        <div className="decision-fs-card-reason">{decision.route_reason}</div>
      )}

      {routes.length > 0 && (
        <div className="decision-fs-routes">
          {routes.map((route, i) => {
            const RouteIcon = ROUTE_ICONS[route.route_type] || TrendingUp;
            return (
              <div key={route.route_type} className={`decision-fs-route ${i === 0 ? 'top' : ''}`}>
                <RouteIcon size={14} />
                <span className="decision-fs-route-name">
                  {ROUTE_LABELS[route.route_type] || route.route_type}
                </span>
                <span className="decision-fs-route-value">
                  ${route.estimated_value?.toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <button
        className="decision-fs-execute"
        onClick={(e) => {
          e.stopPropagation();
          onExecuteItem(item.item_id, ['facebook']);
        }}
      >
        <Zap size={14} />
        Execute Route
      </button>
    </div>
  );
}

export default function DecisionPanel({ items, decisions, agents = {}, onExecuteItem, fullscreen }) {
  const [expandedItem, setExpandedItem] = useState(null);
  const decisionList = useMemo(() => Object.values(decisions), [decisions]);

  const totalValue = useMemo(() => {
    return decisionList.reduce((sum, d) => sum + (d.estimated_best_value || 0), 0);
  }, [decisionList]);

  const hasWinner = decisionList.length > 0;

  const carouselItems = useMemo(() => {
    return items.filter((item) => decisions[item.item_id]);
  }, [items, decisions]);

  const handleExpand = useCallback((item) => {
    if (decisions[item.item_id]) setExpandedItem(item);
  }, [decisions]);

  const renderCarouselItem = useCallback((item, index, isActive, isFocused) => {
    const decision = decisions[item.item_id];
    if (!decision) return null;
    return <DecisionCard item={item} decision={decision} onExecuteItem={onExecuteItem} onExpand={handleExpand} />;
  }, [decisions, onExecuteItem, handleExpand]);

  const useCarousel = carouselItems.length > 1;

  return (
    <div className={`decision-fs ${fullscreen ? 'decision-fs-full' : ''}`}>
      <motion.div
        className="decision-fs-inner"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <div className="decision-fs-header">
          <Trophy size={32} className="decision-fs-trophy" />
          <h2 className="decision-fs-title">Route Decisions</h2>
          <div className={`decision-fs-total ${hasWinner ? 'winner' : ''}`}>
            <div className="decision-fs-total-label">Total Recovered Value</div>
            <AnimatedValue
              value={totalValue}
              prefix="$"
              decimals={2}
              large
              positive
            />
          </div>
        </div>

        {useCarousel ? (
          <div className="decision-carousel-wrap">
            <CircularCarousel
              items={carouselItems}
              renderItem={renderCarouselItem}
              onSelect={(item) => handleExpand(item)}
            />
          </div>
        ) : (
          <AnimatePresence>
            <div className="decision-fs-grid">
              {items.map((item, index) => {
                const decision = decisions[item.item_id];
                if (!decision) return null;
                const Icon = ROUTE_ICONS[decision.best_route] || TrendingUp;
                return (
                  <motion.div
                    key={item.item_id}
                    className="decision-fs-card glass-enhanced shine-on-hover"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.05, duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
                    onClick={() => handleExpand(item)}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="decision-fs-card-header">
                      {item.hero_frame_paths?.[0] && (
                        <img src={item.hero_frame_paths[0]} alt={item.name_guess} className="decision-fs-card-thumb" />
                      )}
                      <div className="decision-fs-card-info">
                        <span className="decision-fs-card-name">{item.name_guess}</span>
                        <Badge variant="success">
                          {ROUTE_LABELS[decision.best_route] || decision.best_route}
                        </Badge>
                      </div>
                    </div>

                    <div className="decision-fs-card-value">
                      <Icon size={20} />
                      <AnimatedValue value={decision.estimated_best_value || 0} prefix="$" decimals={2} positive />
                    </div>

                    {decision.route_reason && (
                      <div className="decision-fs-card-reason">{decision.route_reason}</div>
                    )}

                    {decision?.alternatives && (() => {
                      const seen = new Set();
                      const routes = [decision.winning_bid, ...decision.alternatives]
                        .filter(Boolean)
                        .filter((r) => { if (seen.has(r.route_type)) return false; seen.add(r.route_type); return true; })
                        .filter((r) => r.viable !== false)
                        .slice(0, 3);
                      return (
                        <div className="decision-fs-routes">
                          {routes.map((route, i) => {
                            const RouteIcon = ROUTE_ICONS[route.route_type] || TrendingUp;
                            return (
                              <div key={route.route_type} className={`decision-fs-route ${i === 0 ? 'top' : ''}`}>
                                <RouteIcon size={14} />
                                <span className="decision-fs-route-name">
                                  {ROUTE_LABELS[route.route_type] || route.route_type}
                                </span>
                                <span className="decision-fs-route-value">
                                  ${route.estimated_value?.toFixed(2)}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      );
                    })()}

                    <button
                      className="decision-fs-execute"
                      onClick={(e) => {
                        e.stopPropagation();
                        onExecuteItem(item.item_id, ['facebook']);
                      }}
                    >
                      <Zap size={14} />
                      Execute Route
                    </button>
                  </motion.div>
                );
              })}
            </div>
          </AnimatePresence>
        )}

        {items.length === 0 && (
          <div className="decision-fs-empty">
            <TrendingUp size={32} />
            <p>Waiting for route decisions...</p>
          </div>
        )}
      </motion.div>

      <AnimatePresence>
        {expandedItem && decisions[expandedItem.item_id] && (
          <ItemDetailExpanded
            item={expandedItem}
            decision={decisions[expandedItem.item_id]}
            onClose={() => setExpandedItem(null)}
            onExecuteItem={onExecuteItem}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
