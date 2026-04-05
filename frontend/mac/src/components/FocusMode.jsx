import { useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Clock, Globe, Search, FileEdit, AlertCircle } from 'lucide-react';
import BrowserFeed from './BrowserFeed';
import { PHASE_RESEARCH, CMD_FOCUS_REQUEST, CMD_FOCUS_RELEASE } from '../utils/contracts';

function elapsed(startedAt) {
  if (!startedAt) return '--';
  const s = Math.floor(Date.now() / 1000 - startedAt);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function FocusMode({ agent, screenshotUrl, onClose, send }) {
  const agentId = agent?.agent_id;

  useEffect(() => {
    if (!agentId || !send) return;
    send({ type: CMD_FOCUS_REQUEST, agent_id: agentId });
    return () => send({ type: CMD_FOCUS_RELEASE, agent_id: agentId });
  }, [agentId, send]);

  const handleKey = useCallback((e) => {
    if (e.key === 'Escape') onClose?.();
  }, [onClose]);

  useEffect(() => {
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [handleKey]);

  return (
    <AnimatePresence>
      {agent && (
        <motion.div
          className="fm-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
        >
          <motion.div
            className="fm-panel"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0, transition: { duration: 0.2 } }}
            transition={{ duration: 0.4, ease: [0.32, 0.72, 0, 1] }}
          >
            <div className="fm-header">
              <div className="fm-agent-info">
                <Globe size={16} />
                <span className="fm-platform">{agent.platform}</span>
                <span className={`fm-phase fm-phase-${agent.phase}`}>
                  {agent.phase === PHASE_RESEARCH ? <Search size={12} /> : <FileEdit size={12} />}
                  {agent.phase}
                </span>
              </div>
              <div className="fm-meta">
                <Clock size={12} />
                <span>{elapsed(agent.started_at)}</span>
              </div>
              <button className="fm-close" onClick={onClose} aria-label="Close focus mode">
                <X size={18} />
              </button>
            </div>

            <div className="fm-feed">
              <BrowserFeed screenshotUrl={screenshotUrl} size="full" />
            </div>

            <div className="fm-footer">
              <div className="fm-task">
                {agent.status === 'error' && <AlertCircle size={14} className="fm-error-icon" />}
                <span>{agent.error || agent.task || 'Waiting for task...'}</span>
              </div>
              <span className={`fm-status fm-status-${agent.status}`}>
                {agent.status}
              </span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
