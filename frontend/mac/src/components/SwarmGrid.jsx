import { useMemo } from 'react';
import { motion, LayoutGroup } from 'framer-motion';
import { AlertCircle, Clock } from 'lucide-react';
import BrowserFeed from './BrowserFeed';

const GRID_SLOTS = 12;

function padSlots(record) {
  const list = Object.values(record || {})
    .filter((a) => a && a.agent_id)
    .sort((a, b) => String(a.agent_id).localeCompare(String(b.agent_id)));

  const slots = [];
  for (let i = 0; i < GRID_SLOTS; i++) {
    slots.push(
      list[i]
        ? { ...list[i], _ph: false }
        : { _ph: true, agent_id: `slot-${i}` },
    );
  }
  return slots;
}

function statusLabel(a) {
  if (a._ph) return 'Awaiting agent';
  if (a.status === 'queued') return 'Queued';
  if (a.status === 'running') return 'Running';
  if (a.status === 'navigating') return 'Navigating';
  if (a.status === 'filling') return 'Filling form';
  if (a.status === 'complete') return 'Complete';
  if (a.status === 'error') return 'Error';
  if (a.status === 'blocked') return 'Blocked';
  return a.status || '\u2014';
}

export default function SwarmGrid({
  agents,
  getScreenshotUrl,
  onSelectAgent,
  focusedAgentId,
}) {
  const slots = useMemo(() => padSlots(agents), [agents]);

  return (
    <LayoutGroup>
      <div className="swarm-grid">
        {slots.map((a, i) => {
          const ph = a._ph;
          const shot =
            !ph && a.agent_id ? getScreenshotUrl(a.agent_id) : null;
          const err = !ph && (a.status === 'error' || a.status === 'blocked');
          const active =
            !ph &&
            ['running', 'navigating', 'filling'].includes(a.status);
          const dimmed = focusedAgentId && a.agent_id !== focusedAgentId;

          return (
            <motion.div
              key={a.agent_id}
              layoutId={a.agent_id}
              className={[
                'swarm-card',
                ph && 'swarm-card--ph',
                err && 'swarm-card--err',
                active && 'swarm-card--active',
                dimmed && 'swarm-card--dimmed',
              ]
                .filter(Boolean)
                .join(' ')}
              initial={{ opacity: 0, scale: 0.92 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{
                type: 'spring',
                stiffness: 300,
                damping: 26,
                delay: i * 0.02,
              }}
              onClick={() => !ph && onSelectAgent?.(a)}
            >
              <div className="swarm-card__feed">
                <BrowserFeed url={shot} />
              </div>
              <div className="swarm-card__body">
                <div className="swarm-card__top">
                  <span
                    className="swarm-card__platform"
                    data-platform={ph ? '' : a.platform}
                  >
                    {ph ? '\u2026' : (a.platform || '?').slice(0, 2).toUpperCase()}
                  </span>
                  {!ph && a.phase && (
                    <span
                      className={`swarm-card__phase swarm-card__phase--${a.phase}`}
                    >
                      {a.phase === 'listing' ? 'Listing' : 'Research'}
                    </span>
                  )}
                </div>
                <div className="swarm-card__status">
                  {err && <AlertCircle size={13} />}
                  <span>{statusLabel(a)}</span>
                  {!ph && a.status === 'queued' && <Clock size={11} />}
                </div>
                {!ph && a.task && (
                  <p className="swarm-card__task">{a.task}</p>
                )}
              </div>
            </motion.div>
          );
        })}
      </div>
    </LayoutGroup>
  );
}
