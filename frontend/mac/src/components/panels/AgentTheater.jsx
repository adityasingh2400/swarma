import { useMemo, useState } from 'react';
import {
  Cpu, Search, RefreshCw, Package, Wrench,
  Trophy, MessageSquare,
} from 'lucide-react';
import MissionControl from '../modules/MissionControl';
import { ACTIVE_STATUSES } from '../../utils/contracts';

const STAGE_GROUPS = [
  { id: 'processing', label: 'Processing', icon: Cpu, agents: ['intake'], stage: 1, concurrent: false },
  { id: 'routes', label: 'Route Bidding', icon: Search,
    agents: ['marketplace_resale', 'trade_in', 'return', 'repair_roi'], stage: 2, concurrent: true,
    subLabels: [
      { id: 'marketplace_resale', label: 'Resale', icon: Search },
      { id: 'trade_in', label: 'Trade', icon: RefreshCw },
      { id: 'return', label: 'Return', icon: Package },
      { id: 'repair_roi', label: 'Repair', icon: Wrench },
    ],
  },
  { id: 'posting', label: 'Posting', icon: Trophy, agents: ['route_decider'], stage: 3, concurrent: false },
  { id: 'concierge', label: 'Concierge', icon: MessageSquare, agents: ['concierge'], stage: 4, concurrent: false },
];

function normalizeStatus(rawStatus) {
  if (!rawStatus) return 'idle';
  if (rawStatus === 'agent_started' || rawStatus === 'thinking') return 'thinking';
  if (rawStatus === 'agent_completed' || rawStatus === 'done' || rawStatus === 'complete') return 'done';
  if (rawStatus === 'agent_error' || rawStatus === 'error') return 'error';
  if (rawStatus === 'agent_progress') return 'thinking';
  if (ACTIVE_STATUSES.has(rawStatus)) return 'thinking';
  return rawStatus;
}

function getGroupStatus(group, agents) {
  const statuses = group.agents.map((id) => normalizeStatus(agents[id]?.status));
  if (statuses.some((s) => s === 'thinking')) return 'thinking';
  if (statuses.every((s) => s === 'done')) return 'done';
  if (statuses.some((s) => s === 'done')) return 'partial';
  return 'idle';
}

function getCurrentStageGroup(agents) {
  for (let i = STAGE_GROUPS.length - 1; i >= 0; i--) {
    if (getGroupStatus(STAGE_GROUPS[i], agents) === 'thinking') return i;
  }
  for (let i = STAGE_GROUPS.length - 1; i >= 0; i--) {
    const s = getGroupStatus(STAGE_GROUPS[i], agents);
    if (s === 'done' || s === 'partial') return i;
  }
  return 0;
}

export default function AgentTheater({
  job,
  items,
  bids,
  decisions,
  listings,
  threads,
  agents = {},
  agentsRaw = {},
  agentsByItem = {},
  stage3Plan,
  events,
  lastEvent,
  onExecuteItem,
  onSendReply,
  onStageClick,
  v2Agents = {},
  pipelineStage,
  postingStatus = {},
  send,
  miniPlayer,
  settled,
}) {
  const currentGroupIdx = useMemo(() => getCurrentStageGroup(agents), [agents]);
  const [userSelectedGroup, setUserSelectedGroup] = useState(null);

  const handleStageClick = (stageIndex) => {
    const group = STAGE_GROUPS[stageIndex];
    if (!group) return;
    const status = getGroupStatus(group, agents);
    if (status === 'done' || status === 'partial' || status === 'thinking') {
      setUserSelectedGroup(stageIndex);
      onStageClick?.(stageIndex);
    }
  };

  const mcStageIdx = useMemo(() => {
    const groupIdx = userSelectedGroup != null ? userSelectedGroup : currentGroupIdx;
    const group = STAGE_GROUPS[groupIdx];
    if (!group) return 0;
    return group.stage - 1;
  }, [userSelectedGroup, currentGroupIdx]);

  return (
    <div className="theater-v2">
      {/* Concurrent-aware Pipeline Bar */}
      <div className="agent-bar-v2">
        {STAGE_GROUPS.map((group, i) => {
          const status = getGroupStatus(group, agents);
          const activeGroupIdx = userSelectedGroup != null ? userSelectedGroup : currentGroupIdx;
          const isCurrent = i === activeGroupIdx;
          const isPast = i < activeGroupIdx;
          const isFuture = i > activeGroupIdx;
          const isClickable = status === 'done' || status === 'partial' || status === 'thinking';
          const Icon = group.icon;

          return (
            <div key={group.id} className="agent-bar-v2-segment" style={{ display: 'contents' }}>
              {i > 0 && (
                <div className={`ab2-connector ${isPast ? 'ab2-conn-done' : ''}`}>
                  <div className="ab2-conn-line" />
                  {group.concurrent && (
                    <div className="ab2-fork-indicator">
                      <div className="ab2-fork-line ab2-fork-top" />
                      <div className="ab2-fork-line ab2-fork-bot" />
                    </div>
                  )}
                </div>
              )}

              {group.concurrent && group.subLabels ? (
                <div
                  className={`ab2-parallel-cluster ${isCurrent ? 'ab2-cluster-current' : ''} ${isPast ? 'ab2-cluster-past' : ''} ${isFuture ? 'ab2-cluster-future' : ''} ${isClickable ? 'ab2-clickable' : ''}`}
                  onClick={() => handleStageClick(i)}
                >
                  <div className="ab2-cluster-label">{group.label}</div>
                  <div className="ab2-parallel-tracks">
                    {group.subLabels.map((sub) => {
                      const subStatus = normalizeStatus(agents[sub.id]?.status);
                      const SubIcon = sub.icon;
                      return (
                        <div key={sub.id} className={`ab2-track ab2-track-${subStatus}`}>
                          <div className={`ab2-track-dot ab2-tdot-${subStatus}`}>
                            {subStatus === 'thinking' && <div className="ab2-track-pulse" />}
                            <SubIcon size={12} />
                          </div>
                          <span className="ab2-track-label">{sub.label}</span>
                          {subStatus === 'done' && <span className="ab2-track-check">✓</span>}
                          {subStatus === 'thinking' && <span className="ab2-track-spin" />}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div
                  className={[
                    'ab2-node',
                    isCurrent && 'ab2-current',
                    isPast && 'ab2-past',
                    isFuture && 'ab2-future',
                    status === 'thinking' && 'ab2-thinking',
                    status === 'done' && 'ab2-done',
                    isClickable && 'ab2-clickable',
                  ].filter(Boolean).join(' ')}
                  onClick={() => handleStageClick(i)}
                >
                  <div className="ab2-icon-ring">
                    <Icon size={isCurrent ? 18 : 14} />
                  </div>
                  <span className="ab2-label">{group.label}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Mission Control Content */}
      <div className="theater-content">
        <MissionControl
          agents={agents}
          agentsRaw={agentsRaw}
          agentsByItem={agentsByItem}
          stage3Plan={stage3Plan}
          items={items}
          decisions={decisions}
          bids={bids}
          job={job}
          listings={listings}
          onExecuteItem={onExecuteItem}
          overrideStageIdx={mcStageIdx}
          v2Agents={v2Agents}
          pipelineStage={pipelineStage}
          postingStatus={postingStatus}
          send={send}
          miniPlayer={miniPlayer}
          settled={settled}
        />
      </div>
    </div>
  );
}
