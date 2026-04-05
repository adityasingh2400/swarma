import { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Globe, Search, FileEdit, AlertCircle, Clock, Loader } from 'lucide-react';
import BrowserFeed from './BrowserFeed';
import {
  ACTIVE_STATUSES, STATUS_QUEUED, STATUS_ERROR, STATUS_BLOCKED,
  STATUS_COMPLETE, PHASE_RESEARCH, PHASE_LISTING,
} from '../utils/contracts';

const PLATFORM_ICONS = { facebook: Globe, depop: Globe, amazon: Globe };
const PHASE_ICON = { [PHASE_RESEARCH]: Search, [PHASE_LISTING]: FileEdit };

function statusLabel(status) {
  const labels = {
    queued: 'Queued', running: 'Running', navigating: 'Navigating',
    filling: 'Filling form', complete: 'Complete', error: 'Error', blocked: 'Blocked',
  };
  return labels[status] || status;
}

function StatusIndicator({ status }) {
  if (status === STATUS_QUEUED) return <Clock size={12} className="sg-status-icon sg-status-queued" />;
  if (status === STATUS_ERROR || status === STATUS_BLOCKED) return <AlertCircle size={12} className="sg-status-icon sg-status-error" />;
  if (status === STATUS_COMPLETE) return <div className="sg-status-dot sg-dot-complete" />;
  if (ACTIVE_STATUSES.has(status)) return <Loader size={12} className="sg-status-icon sg-status-active" />;
  return null;
}

export default function SwarmGrid({ v2Agents, screenshots, onFocusAgent, focusedAgentId, filterPhase }) {
  const agentList = useMemo(
    () => Object.values(v2Agents || {})
      .filter((a) => !filterPhase || a.phase === filterPhase)
      .sort((a, b) => {
        if (a.phase !== b.phase) return a.phase === PHASE_RESEARCH ? -1 : 1;
        return (a.agent_id || '').localeCompare(b.agent_id || '');
      }),
    [v2Agents, filterPhase],
  );

  if (agentList.length === 0) return null;

  return (
    <div className={`sg-grid ${focusedAgentId ? 'sg-grid-dimmed' : ''}`}>
      <AnimatePresence>
        {agentList.map((agent, i) => {
          const PlatIcon = PLATFORM_ICONS[agent.platform] || Globe;
          const PhaseIcon = PHASE_ICON[agent.phase] || Search;
          const shot = screenshots instanceof Map
            ? screenshots.get(agent.agent_id)
            : screenshots?.[agent.agent_id];
          const isError = agent.status === STATUS_ERROR || agent.status === STATUS_BLOCKED;
          const isActive = ACTIVE_STATUSES.has(agent.status);
          const isDone = agent.status === STATUS_COMPLETE;
          const isQueued = agent.status === STATUS_QUEUED;

          return (
            <motion.div
              key={agent.agent_id}
              layoutId={agent.agent_id}
              className={[
                'sg-card',
                isError && 'sg-card-error',
                isActive && 'sg-card-active',
                isDone && 'sg-card-done',
                isQueued && 'sg-card-queued',
              ].filter(Boolean).join(' ')}
              initial={{ opacity: 0, scale: 0.85, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.85, transition: { duration: 0.2 } }}
              transition={{ duration: 0.4, ease: [0.32, 0.72, 0, 1], delay: i * 0.05 }}
              onClick={() => onFocusAgent?.(agent.agent_id)}
            >
              <div className="sg-card-header">
                <div className="sg-platform">
                  <PlatIcon size={14} />
                  <span>{agent.platform}</span>
                </div>
                <span className={`sg-phase-badge sg-phase-${agent.phase}`}>
                  <PhaseIcon size={10} />
                  {agent.phase}
                </span>
              </div>

              <div className="sg-card-feed">
                <BrowserFeed screenshotUrl={shot?.url} size="thumbnail" />
              </div>

              <div className="sg-card-footer">
                <StatusIndicator status={agent.status} />
                <span className="sg-status-text">{statusLabel(agent.status)}</span>
                {isError && agent.error && (
                  <span className="sg-error-hint" title={agent.error}>!</span>
                )}
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
