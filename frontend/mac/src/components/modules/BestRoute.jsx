import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { ShoppingBag, RefreshCw, Wrench, Trophy, Clock, RotateCcw } from 'lucide-react';
import AnimatedValue from '../shared/AnimatedValue';

const ROUTE_ICONS = {
  sell_as_is: ShoppingBag,
  trade_in: RefreshCw,
  repair_then_sell: Wrench,
  return: RotateCcw,
};

const ROUTE_LABELS = {
  sell_as_is: 'Sell As-Is',
  trade_in: 'Trade-In',
  repair_then_sell: 'Repair & Resell',
  return: 'Return',
};

const EFFORT_DOTS = { minimal: 1, low: 2, moderate: 3, high: 4 };

const SPEED_LABELS = {
  instant: 'Instant',
  days: 'Fast',
  week: 'Medium',
  weeks: 'Slow',
  month_plus: 'Very Slow',
};

const DEMO_ROUTES = [
  {
    route_type: 'repair_then_sell',
    estimated_value: 672.03,
    effort: 'high',
    speed: 'weeks',
    explanation: 'Screen fix + battery swap unlocks $152 extra recovery',
    _winner: true,
  },
  {
    route_type: 'sell_as_is',
    estimated_value: 520,
    effort: 'low',
    speed: 'days',
    explanation: 'Strong comp data supports this price point',
    _winner: false,
  },
  {
    route_type: 'trade_in',
    estimated_value: 485,
    effort: 'minimal',
    speed: 'days',
    explanation: 'Guaranteed payout, zero effort',
    _winner: false,
  },
  {
    route_type: 'bundle_then_sell',
    estimated_value: 620,
    effort: 'moderate',
    speed: 'weeks',
    explanation: 'Higher combined value but slower to sell',
    _winner: false,
  },
];

export default function BestRoute({ decisions }) {
  const { routes, winnerType } = useMemo(() => {
    const decisionList = Object.values(decisions);
    const decision = decisionList[0];

    if (decision?.winning_bid || decision?.alternatives?.length > 0) {
      const combined = [
        decision.winning_bid,
        ...(decision.alternatives || []),
      ].filter(Boolean);
      return {
        routes: combined,
        winnerType: decision.best_route,
      };
    }

    return {
      routes: DEMO_ROUTES,
      winnerType: DEMO_ROUTES.find((r) => r._winner)?.route_type,
    };
  }, [decisions]);

  return (
    <div className="best-route">
      <div className="br-ladder">
        {routes.map((route, index) => {
          const Icon = ROUTE_ICONS[route.route_type] || ShoppingBag;
          const isWinner = route.route_type === winnerType;
          const isLoser = !isWinner && winnerType != null;
          const effortDots = EFFORT_DOTS[route.effort] || 2;

          return (
            <motion.div
              key={route.route_type}
              className={`br-route-card ${isWinner ? 'winner' : ''} ${isLoser ? 'loser' : ''}`}
              initial={{ opacity: 0, x: -20 }}
              animate={{
                opacity: isLoser ? 0.4 : 1,
                x: 0,
                scale: isWinner ? 1.02 : isLoser ? 0.97 : 1,
              }}
              transition={{
                delay: index * 0.05,
                duration: 0.4,
                ease: [0.32, 0.72, 0, 1],
              }}
            >
              <div className="br-route-icon">
                {isWinner ? (
                  <Trophy size={20} color="var(--primary)" />
                ) : (
                  <Icon size={20} color="var(--text-tertiary)" />
                )}
              </div>

              <div className="br-route-info">
                <div className="br-route-name">
                  {ROUTE_LABELS[route.route_type] || route.route_type}
                </div>
                <div className="br-route-reason">{route.explanation}</div>
                <div className="br-route-metrics">
                  <div className="br-metric">
                    <Clock size={10} />
                    {SPEED_LABELS[route.speed] || route.speed}
                  </div>
                  <div className="br-metric">
                    <span className="effort-dots">
                      {[1, 2, 3, 4, 5].map((d) => (
                        <span
                          key={d}
                          className={`effort-dot ${d <= effortDots ? 'filled' : ''}`}
                        />
                      ))}
                    </span>
                  </div>
                </div>
              </div>

              <div className="br-route-value">
                <div
                  className="br-route-amount"
                  style={{ color: isWinner ? 'var(--success)' : 'var(--text-primary)' }}
                >
                  <AnimatedValue value={route.estimated_value} prefix="$" decimals={0} />
                </div>
                <div className="br-route-label">expected</div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
