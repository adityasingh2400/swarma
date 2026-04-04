import { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Zap, TrendingUp, ShoppingBag, RefreshCw, Wrench, RotateCcw, Trophy, CheckCircle2 } from 'lucide-react';
import AnimatedValue from '../shared/AnimatedValue';
import Badge from '../shared/Badge';

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

export default function DecisionPanel({ items, decisions, agents = {}, onExecuteItem, fullscreen }) {
  const decisionList = useMemo(() => Object.values(decisions), [decisions]);

  const totalValue = useMemo(() => {
    return decisionList.reduce((sum, d) => sum + (d.estimated_best_value || 0), 0);
  }, [decisionList]);

  const hasWinner = decisionList.length > 0;

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

        <AnimatePresence>
          <div className="decision-fs-grid">
            {items.map((item, index) => {
              const decision = decisions[item.item_id];
              if (!decision) return null;
              const Icon = ROUTE_ICONS[decision.best_route] || TrendingUp;
              return (
                <motion.div
                  key={item.item_id}
                  className="decision-fs-card"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.1, type: 'spring', stiffness: 200, damping: 22 }}
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
                    onClick={() => onExecuteItem(item.item_id, ['ebay', 'mercari'])}
                  >
                    <Zap size={14} />
                    Execute Route
                  </button>
                </motion.div>
              );
            })}
          </div>
        </AnimatePresence>

        {items.length === 0 && (
          <div className="decision-fs-empty">
            <TrendingUp size={32} />
            <p>Waiting for route decisions...</p>
          </div>
        )}
      </motion.div>
    </div>
  );
}
