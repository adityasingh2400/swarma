import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { Smartphone, ShoppingBag, ArrowRight, Sparkles } from 'lucide-react';
import AnimatedValue from '../shared/AnimatedValue';
import Badge from '../shared/Badge';

const DEMO_DEFECTS = [
  { description: 'Cracked screen corner', source: 'camera', severity: 'major' },
  { description: 'Battery health 82%', source: 'spoken', severity: 'minor' },
];

const DEMO_PARTS = [
  { part_name: 'OEM Screen Assembly — iPhone 14 Pro Max', part_price: 89.99, source: 'Amazon', part_url: '#', part_image_url: null },
  { part_name: 'Replacement Battery Kit — iPhone 14 Pro', part_price: 34.99, source: 'Amazon', part_url: '#', part_image_url: null },
  { part_name: 'Repair Tool Kit — 38pc Professional', part_price: 12.99, source: 'Amazon', part_url: '#', part_image_url: null },
];

const DEMO_PAYOFF = {
  as_is_value: 520,
  repair_cost: 137.97,
  post_repair_value: 810,
  net_gain_unlocked: 152.03,
};

export default function RepairSweep({ items, bids }) {
  const { defects, parts, payoff } = useMemo(() => {
    const allBids = Object.values(bids || {}).flat();
    const repairBid = allBids.find((b) => b.route_type === 'repair_then_sell');

    if (repairBid) {
      const item = items.find((i) => i.item_id === repairBid.item_id);
      const itemDefects = [
        ...(item?.visible_defects || []),
        ...(item?.spoken_defects || []).map((s) => ({ description: s, source: 'spoken', severity: 'minor' })),
      ];
      return {
        defects: itemDefects.length > 0 ? itemDefects : DEMO_DEFECTS,
        parts: repairBid.repair_candidates?.length > 0 ? repairBid.repair_candidates : DEMO_PARTS,
        payoff: {
          as_is_value: repairBid.as_is_value ?? DEMO_PAYOFF.as_is_value,
          repair_cost: repairBid.repair_cost ?? DEMO_PAYOFF.repair_cost,
          post_repair_value: repairBid.post_repair_value ?? DEMO_PAYOFF.post_repair_value,
          net_gain_unlocked: repairBid.net_gain_unlocked ?? DEMO_PAYOFF.net_gain_unlocked,
        },
      };
    }

    const item = items[0];
    const itemDefects = item
      ? [
          ...(item.visible_defects || []),
          ...(item.spoken_defects || []).map((s) => ({ description: s, source: 'spoken', severity: 'minor' })),
        ]
      : [];

    return {
      defects: itemDefects.length > 0 ? itemDefects : DEMO_DEFECTS,
      parts: DEMO_PARTS,
      payoff: DEMO_PAYOFF,
    };
  }, [items, bids]);

  return (
    <div className="repair-sweep">
      <div className="rs-defect-panel">
        <div className="rs-item-image">
          <Smartphone size={48} />
          {defects.map((defect, i) => (
            <motion.span
              key={i}
              className="rs-defect-tag"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.3 + i * 0.2 }}
            >
              {defect.description}
            </motion.span>
          ))}
        </div>
      </div>

      <div className="rs-parts-panel">
        <div className="rs-parts-title">Replacement Parts</div>
        {parts.map((part, index) => (
          <motion.div
            key={part.part_name}
            className="rs-part-card"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + index * 0.1 }}
          >
            <div className="rs-part-image">
              {part.part_image_url ? (
                <img src={part.part_image_url} alt={part.part_name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ) : (
                <ShoppingBag size={22} />
              )}
            </div>
            <div className="rs-part-info">
              <div className="rs-part-name">{part.part_name}</div>
              <div className="rs-part-price">${part.part_price.toFixed(2)}</div>
            </div>
            <Badge platform={part.source?.toLowerCase() || 'amazon'} />
          </motion.div>
        ))}
      </div>

      <motion.div
        className="rs-payoff-panel"
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.4 }}
      >
        <div className="rs-payoff-title">Payoff Analysis</div>
        <div className="rs-payoff-row">
          <span className="rs-payoff-label">Sell as-is</span>
          <span className="rs-payoff-value" style={{ color: 'var(--text-secondary)' }}>
            ${payoff.as_is_value}
          </span>
        </div>
        <div className="rs-payoff-row">
          <span className="rs-payoff-label">Repair cost</span>
          <span className="rs-payoff-value" style={{ color: 'var(--danger)' }}>
            -${payoff.repair_cost.toFixed(2)}
          </span>
        </div>
        <div className="rs-payoff-row">
          <span className="rs-payoff-label">Post-repair value</span>
          <span className="rs-payoff-value" style={{ color: 'var(--text-primary)' }}>
            ${payoff.post_repair_value}
          </span>
        </div>

        <motion.div
          className="rs-net-gain"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.8, duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
        >
          <div className="rs-net-gain-label">
            <Sparkles size={12} style={{ display: 'inline', marginRight: 4 }} />
            Net Gain Unlocked
          </div>
          <AnimatedValue
            value={payoff.net_gain_unlocked}
            prefix="+$"
            decimals={2}
            className="rs-net-gain-value"
          />
        </motion.div>
      </motion.div>
    </div>
  );
}
