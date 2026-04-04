import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { DollarSign, Clock, Zap, Star } from 'lucide-react';
import Badge from '../shared/Badge';

const DEMO_QUOTES = [
  { provider: 'Decluttr', payout: 485, speed: 'days', effort: 'low', confidence: 0.88, icon: '📦' },
  { provider: 'Back Market', payout: 520, speed: 'week', effort: 'low', confidence: 0.92, icon: '🔄' },
  { provider: 'Swappa Direct', payout: 510, speed: 'days', effort: 'moderate', confidence: 0.85, icon: '🏪' },
  { provider: 'Apple Trade-In', payout: 430, speed: 'week', effort: 'low', confidence: 0.95, icon: '🍎' },
  { provider: 'GameStop', payout: 380, speed: 'instant', effort: 'low', confidence: 0.90, icon: '🎮' },
];

const SPEED_LABELS = {
  instant: 'Instant',
  days: '2–3 days',
  week: '~1 week',
  weeks: '2–3 weeks',
  month_plus: '1+ month',
};

export default function QuoteSweep({ bids }) {
  const quotes = useMemo(() => {
    const allBids = Object.values(bids).flat();
    const tradeInBids = allBids.filter((b) => b.route_type === 'trade_in');
    const realQuotes = tradeInBids.flatMap((b) => b.trade_in_quotes || []);
    if (realQuotes.length > 0) {
      return realQuotes.sort((a, b) => (b.payout || 0) - (a.payout || 0));
    }
    return DEMO_QUOTES;
  }, [bids]);

  const bestProvider = quotes.reduce(
    (best, q) => ((q.payout || 0) > (best?.payout || 0) ? q : best),
    null,
  )?.provider;

  return (
    <div className="quote-sweep">
      {quotes.map((quote, index) => {
        const isBest = quote.provider === bestProvider;
        return (
          <motion.div
            key={quote.provider}
            className={`qs-card ${isBest ? 'best-quote' : ''}`}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.08, duration: 0.3 }}
          >
            <div className="qs-provider">
              {quote.icon || '💰'}
            </div>
            <div className="qs-info">
              <div className="qs-provider-name">
                {quote.provider}
                {isBest && (
                  <Star
                    size={12}
                    fill="var(--success)"
                    color="var(--success)"
                    style={{ marginLeft: 6, verticalAlign: 'middle' }}
                  />
                )}
              </div>
              <div className="qs-meta">
                <span className="qs-meta-item">
                  <Clock size={10} style={{ display: 'inline', marginRight: 3 }} />
                  {SPEED_LABELS[quote.speed] || quote.speed}
                </span>
                <span className="qs-meta-item">
                  <Zap size={10} style={{ display: 'inline', marginRight: 3 }} />
                  {quote.effort} effort
                </span>
              </div>
            </div>
            <div className="qs-payout">
              <div
                className="qs-payout-amount animated-value"
                style={{ color: isBest ? 'var(--success)' : 'var(--text-primary)' }}
              >
                ${quote.payout}
              </div>
              <div className="qs-payout-label">payout</div>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
