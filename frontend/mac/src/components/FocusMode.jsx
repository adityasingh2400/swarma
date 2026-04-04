import { useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { X } from 'lucide-react';
import BrowserFeed from './BrowserFeed';

function elapsed(startedAt) {
  if (startedAt == null) return '\u2014';
  const s = typeof startedAt === 'number' ? startedAt : Number(startedAt);
  if (Number.isNaN(s)) return '\u2014';
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - s));
  const m = Math.floor(sec / 60);
  const r = sec % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

export default function FocusMode({ agent, onClose, getScreenshotUrl, sendWs }) {
  const url = agent?.agent_id ? getScreenshotUrl(agent.agent_id) : null;

  useEffect(() => {
    if (!agent?.agent_id) return;
    sendWs?.({ type: 'focus:request', agent_id: agent.agent_id });
    return () => {
      sendWs?.({ type: 'focus:release', agent_id: agent.agent_id });
    };
  }, [agent?.agent_id, sendWs]);

  const onKey = useCallback(
    (e) => {
      if (e.key === 'Escape') onClose?.();
    },
    [onClose],
  );

  useEffect(() => {
    if (!agent) return;
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [agent, onKey]);

  if (!agent) return null;

  return (
    <motion.div
      className="focus-root"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <button
        type="button"
        className="focus-root__backdrop"
        aria-label="Close"
        onClick={() => onClose?.()}
      />
      <motion.div
        className="focus-panel"
        layoutId={agent.agent_id}
        role="dialog"
        aria-modal="true"
        transition={{ type: 'spring', stiffness: 260, damping: 28 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="focus-panel__toolbar">
          <div>
            <h2 className="focus-panel__title">
              <span className="focus-panel__platform">
                {(agent.platform || 'Agent').toUpperCase()}
              </span>
              <span className="focus-panel__id">{agent.agent_id}</span>
            </h2>
            <p className="focus-panel__meta">
              <span>{agent.phase === 'listing' ? 'Listing' : 'Research'}</span>
              <span className="focus-panel__sep">\u00b7</span>
              <span>{elapsed(agent.started_at)}</span>
            </p>
          </div>
          <button
            type="button"
            className="focus-panel__close"
            onClick={() => onClose?.()}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>
        <div className="focus-panel__feed">
          <BrowserFeed url={url} large />
        </div>
        {agent.task && <p className="focus-panel__task">{agent.task}</p>}
      </motion.div>
    </motion.div>
  );
}
