import { motion } from 'framer-motion';
import { Wifi, WifiOff, Activity } from 'lucide-react';
import { PIPELINE_STAGES } from '../contracts.js';

const STAGE_LABELS = {
  video: 'Video',
  analysis: 'Analysis',
  research: 'Research',
  decision: 'Decision',
  listing: 'Listing',
};

function stageIdx(id) {
  const i = PIPELINE_STAGES.indexOf(id);
  return i < 0 ? 0 : i;
}

export default function PipelineHeader({
  stage,
  pipelineStats,
  itemCount = 0,
  connected,
  activeAgentCount = 0,
  totalAgentCount = 0,
}) {
  const active = stageIdx(stage);
  const pct = (active / Math.max(1, PIPELINE_STAGES.length - 1)) * 100;

  const detail =
    stage === 'research' && pipelineStats?.researchTotal > 0
      ? `${pipelineStats.researchDone}/${pipelineStats.researchTotal} research done`
      : stage === 'listing' && pipelineStats?.listingTotal > 0
        ? `${pipelineStats.listingDone}/${pipelineStats.listingTotal} listing done`
        : stage === 'analysis'
          ? itemCount > 0
            ? `${itemCount} item${itemCount !== 1 ? 's' : ''} found`
            : 'Analyzing video\u2026'
          : '';

  return (
    <header className="pipeline-pill">
      <div className="pipeline-pill__steps">
        {PIPELINE_STAGES.map((s, i) => {
          const done = i < active;
          const cur = i === active;
          return (
            <div
              key={s}
              className={[
                'pipeline-dot',
                done && 'pipeline-dot--done',
                cur && 'pipeline-dot--cur',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <span className="pipeline-dot__circle" />
              <span className="pipeline-dot__label">
                {STAGE_LABELS[s] || s}
              </span>
            </div>
          );
        })}
        <div className="pipeline-pill__track">
          <motion.div
            className="pipeline-pill__fill"
            initial={false}
            animate={{ width: `${pct}%` }}
            transition={{ type: 'spring', stiffness: 120, damping: 26 }}
          />
        </div>
      </div>

      <div className="pipeline-pill__meta">
        {detail && <span className="pipeline-pill__detail">{detail}</span>}

        {totalAgentCount > 0 && (
          <span className="pipeline-pill__agents">
            <Activity size={12} />
            {activeAgentCount > 0
              ? `${activeAgentCount} active`
              : `${totalAgentCount} total`}
          </span>
        )}

        <span
          className={`pipeline-pill__conn ${connected ? 'pipeline-pill__conn--on' : ''}`}
        >
          {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
          {connected ? 'Live' : 'Offline'}
        </span>
      </div>
    </header>
  );
}
