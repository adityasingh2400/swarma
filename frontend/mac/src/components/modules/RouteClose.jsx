import { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, X } from 'lucide-react';
import AnimatedValue from '../shared/AnimatedValue';
import Badge from '../shared/Badge';

const DEMO_WINNER = {
  platform: 'facebook',
  buyer: 'Sarah M.',
  amount: 770,
};

const DEMO_LOSERS = [
];

const DEMO_TOTAL = 770;

export default function RouteClose({ listings, decisions }) {
  const { winner, losers, total } = useMemo(() => {
    const allListings = Object.values(listings || {});
    const allPlatforms = allListings.flatMap((l) =>
      (l.platform_listings || []).map((pl) => ({ ...pl, item_id: l.item_id }))
    );

    const archived = allPlatforms.find((pl) => pl.status === 'archived');

    if (archived) {
      const otherPlatforms = allPlatforms
        .filter((pl) => pl !== archived)
        .map((pl) => ({
          platform: pl.platform,
          reason: pl.status === 'failed' ? 'Failed' : 'Outbid',
        }));

      const decision = (decisions || {})[archived.item_id];

      return {
        winner: {
          platform: archived.platform,
          buyer: null,
          amount: decision?.estimated_best_value || 0,
        },
        losers: otherPlatforms,
        total: decision?.estimated_best_value || 0,
      };
    }

    const totalRecovered = Object.values(decisions || {}).reduce(
      (sum, d) => sum + (d.estimated_best_value || 0),
      0,
    );

    return {
      winner: DEMO_WINNER,
      losers: DEMO_LOSERS,
      total: totalRecovered || DEMO_TOTAL,
    };
  }, [listings, decisions]);

  return (
    <div className="route-close">
      <AnimatePresence>
        {losers.map((loser, index) => (
          <motion.div
            key={loser.platform}
            className="rc-loser"
            initial={{ opacity: 1, scale: 1, x: 0 }}
            animate={{ opacity: 0.3, scale: 0.9 }}
            exit={{ opacity: 0, x: index % 2 === 0 ? -100 : 100, scale: 0.5, transition: { duration: 0.2 } }}
            transition={{ delay: index * 0.05, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
          >
            <Badge platform={loser.platform} />
            <div className="rc-loser-name">{loser.reason}</div>
          </motion.div>
        ))}
      </AnimatePresence>

      <motion.div
        className="rc-winner"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.5, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
      >
        <motion.div
          className="rc-winner-check"
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.8, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
        >
          <CheckCircle size={28} />
        </motion.div>
        <div className="rc-winner-platform">
          <Badge platform={winner.platform} />
          {winner.buyer && (
            <span style={{ marginLeft: 8, color: 'var(--text-secondary)', fontSize: 14, fontWeight: 400 }}>
              {winner.buyer}
            </span>
          )}
        </div>
        <div className="rc-winner-amount">
          <AnimatedValue value={winner.amount} prefix="$" decimals={0} />
        </div>
      </motion.div>

      <motion.div
        className="rc-total-bar"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1 }}
      >
        <span className="rc-total-label">Total Recovered</span>
        <AnimatedValue
          value={total}
          prefix="$"
          decimals={2}
          className="rc-total-value"
        />
      </motion.div>
    </div>
  );
}
