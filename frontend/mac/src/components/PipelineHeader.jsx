import { useMemo } from 'react';
import { Video, ScanSearch, Search, GitBranch, FileEdit, Check } from 'lucide-react';
import { ACTIVE_STATUSES, STATUS_COMPLETE, PHASE_RESEARCH, PHASE_LISTING } from '../utils/contracts';

const STAGES = [
  { id: 'intake',   label: 'Video',    icon: Video },
  { id: 'analysis', label: 'Analysis', icon: ScanSearch },
  { id: 'research', label: 'Research', icon: Search },
  { id: 'decision', label: 'Decision', icon: GitBranch },
  { id: 'listing',  label: 'Listing',  icon: FileEdit },
];

function stageIndex(stageId) {
  return STAGES.findIndex((s) => s.id === stageId);
}

export default function PipelineHeader({ pipelineStage, v2Agents }) {
  const activeIdx = useMemo(() => {
    const idx = stageIndex(pipelineStage);
    if (idx >= 0) return idx;
    const agents = Object.values(v2Agents || {});
    if (agents.some((a) => a.phase === PHASE_LISTING)) return 4;
    if (agents.some((a) => a.phase === PHASE_RESEARCH)) return 2;
    return 0;
  }, [pipelineStage, v2Agents]);

  const counts = useMemo(() => {
    const agents = Object.values(v2Agents || {});
    const research = agents.filter((a) => a.phase === PHASE_RESEARCH);
    const listing = agents.filter((a) => a.phase === PHASE_LISTING);
    return {
      researchDone: research.filter((a) => a.status === STATUS_COMPLETE).length,
      researchTotal: research.length,
      listingDone: listing.filter((a) => a.status === STATUS_COMPLETE).length,
      listingTotal: listing.length,
    };
  }, [v2Agents]);

  return (
    <div className="ph-bar">
      {STAGES.map((stage, i) => {
        const Icon = stage.icon;
        const isComplete = i < activeIdx;
        const isActive = i === activeIdx;
        const isFuture = i > activeIdx;

        let countLabel = null;
        if (stage.id === 'research' && counts.researchTotal > 0) {
          countLabel = `${counts.researchDone}/${counts.researchTotal}`;
        } else if (stage.id === 'listing' && counts.listingTotal > 0) {
          countLabel = `${counts.listingDone}/${counts.listingTotal}`;
        }

        return (
          <div key={stage.id} className="ph-stage-wrapper">
            {i > 0 && (
              <div className={`ph-connector ${isComplete || isActive ? 'ph-connector-active' : ''}`} />
            )}
            <div
              className={[
                'ph-stage',
                isComplete && 'ph-stage-complete',
                isActive && 'ph-stage-active',
                isFuture && 'ph-stage-future',
              ].filter(Boolean).join(' ')}
            >
              <div className="ph-icon-ring">
                {isComplete ? <Check size={14} /> : <Icon size={14} />}
              </div>
              <span className="ph-label">{stage.label}</span>
              {countLabel && <span className="ph-count">{countLabel}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
