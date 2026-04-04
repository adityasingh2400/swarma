import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { Package, ArrowDown, Layers } from 'lucide-react';
import AnimatedValue from '../shared/AnimatedValue';

const DEMO_BUNDLE_ITEMS = [
  { item_id: 'b1', name_guess: 'iPhone 14 Pro Max', value: 520 },
  { item_id: 'b2', name_guess: 'AirPods Pro 2', value: 120 },
  { item_id: 'b3', name_guess: 'Apple Watch S8', value: 180 },
];

const DEMO_SEPARATE_VALUE = 820;
const DEMO_COMBINED_VALUE = 920;

export default function BundleMerge({ items, bids, decisions }) {
  const { bundleItems, separateTotal, bundleValue } = useMemo(() => {
    const allBids = Object.values(bids || {}).flat();
    const bundleBid = allBids.find((b) => b.route_type === 'bundle_then_sell');

    if (bundleBid) {
      const bundledIds = bundleBid.bundled_item_ids || [];
      const matched = bundledIds
        .map((id) => {
          const item = items.find((i) => i.item_id === id);
          const decision = (decisions || {})[id];
          return {
            item_id: id,
            name_guess: item?.name_guess || id,
            value: decision?.estimated_best_value || 0,
          };
        });

      return {
        bundleItems: matched.length > 0 ? matched : DEMO_BUNDLE_ITEMS,
        separateTotal: bundleBid.separate_value ?? DEMO_SEPARATE_VALUE,
        bundleValue: bundleBid.combined_value ?? DEMO_COMBINED_VALUE,
      };
    }

    if (items.length > 1) {
      const mapped = items.map((i) => {
        const decision = (decisions || {})[i.item_id];
        return {
          item_id: i.item_id,
          name_guess: i.name_guess,
          value: decision?.estimated_best_value || 0,
        };
      });
      const sep = mapped.reduce((s, i) => s + i.value, 0);
      return {
        bundleItems: mapped,
        separateTotal: sep,
        bundleValue: Math.round(sep * 1.12),
      };
    }

    return {
      bundleItems: DEMO_BUNDLE_ITEMS,
      separateTotal: DEMO_SEPARATE_VALUE,
      bundleValue: DEMO_COMBINED_VALUE,
    };
  }, [items, bids, decisions]);

  return (
    <div className="bundle-merge">
      <div className="bm-items-row">
        {bundleItems.map((item, index) => (
          <motion.div
            key={item.item_id}
            className="bm-item-card"
            initial={{ opacity: 0, y: -20, x: index % 2 === 0 ? -30 : 30 }}
            animate={{ opacity: 1, y: 0, x: 0 }}
            transition={{ delay: index * 0.12, type: 'spring', stiffness: 150 }}
          >
            <div className="bm-item-image">
              <Package size={28} />
            </div>
            <div className="bm-item-name">{item.name_guess}</div>
            <motion.div
              className="bm-item-value"
              animate={{ textDecoration: 'line-through', color: 'var(--text-tertiary)' }}
              transition={{ delay: 0.8 + index * 0.1 }}
            >
              ${item.value}
            </motion.div>
          </motion.div>
        ))}
      </div>

      <motion.div
        className="bm-arrow"
        initial={{ opacity: 0, scale: 0 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.6, type: 'spring' }}
      >
        <ArrowDown size={28} />
      </motion.div>

      <motion.div
        className="bm-bundle-card"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 1, type: 'spring', stiffness: 120 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 8 }}>
          <Layers size={18} color="var(--primary)" />
          <span className="bm-bundle-label">Bundle Deal</span>
        </div>
        <AnimatedValue value={bundleValue} prefix="$" className="bm-bundle-value" />
        <motion.div
          style={{ fontSize: 12, color: 'var(--success)', marginTop: 6, fontWeight: 600 }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.3 }}
        >
          +${bundleValue - separateTotal} more than selling separately
        </motion.div>
      </motion.div>
    </div>
  );
}
