import { useState, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity } from 'lucide-react';
import Layout from './components/Layout';
import ReRouteLogo from './components/ReRouteLogo';
import ListingSimulationModal from './components/modules/ListingSimulationModal';
import ExecuteRouteAnimation from './components/modules/ExecuteRouteAnimation';
import { useJob } from './hooks/useJob';
import { useScreenshots } from './hooks/useScreenshots';
import { useMockMode } from './utils/mockData';
import { ACTIVE_STATUSES } from './utils/contracts';

export default function App() {
  const [jobId, setJobId] = useState(null);
  const mock = useMockMode();

  const {
    job: realJob,
    items: realItems,
    bids: realBids,
    decisions: realDecisions,
    listings,
    threads,
    agents: realAgents,
    agentsRaw: realAgentsRaw,
    agentsByItem: realAgentsByItem,
    stage3Plan: realStage3Plan,
    connected: realConnected,
    events: realEvents,
    lastEvent,
    uploadAndStart,
    executeItem,
    sendReply,
    v2Agents: realV2Agents,
    pipelineStage: realPipelineStage,
    send: realSend,
  } = useJob(mock.isMock ? null : jobId);

  const { screenshots: realScreenshots } = useScreenshots(mock.isMock ? null : jobId);

  const job = mock.isMock ? mock.job : realJob;
  const items = mock.isMock ? mock.items : realItems;
  const v2Agents = mock.isMock ? mock.v2Agents : realV2Agents;
  const pipelineStage = mock.isMock ? mock.pipelineStage : realPipelineStage;
  const screenshots = mock.isMock ? mock.screenshots : realScreenshots;
  const send = mock.isMock ? mock.send : realSend;
  const connected = mock.isMock ? true : realConnected;
  const agents = mock.isMock ? mock.agents : realAgents;
  const agentsRaw = mock.isMock ? mock.agentsRaw : realAgentsRaw;
  const agentsByItem = mock.isMock ? mock.agentsByItem : realAgentsByItem;
  const stage3Plan = mock.isMock ? mock.stage3Plan : realStage3Plan;
  const bids = mock.isMock ? mock.bids : realBids;
  const decisions = mock.isMock ? mock.decisions : realDecisions;
  const events = mock.isMock ? mock.events : realEvents;

  const agentSummary = useMemo(() => {
    const entries = Object.values(agents);
    const v2Entries = Object.values(v2Agents);
    const active = entries.filter((a) => ['thinking', 'agent_started', 'agent_progress'].includes(a.status)).length
      + v2Entries.filter((a) => ACTIVE_STATUSES.has(a.status)).length;
    const done = entries.filter((a) => ['done', 'agent_completed'].includes(a.status)).length
      + v2Entries.filter((a) => a.status === 'complete').length;
    const total = entries.length + v2Entries.length;
    return { active, done, total };
  }, [agents, v2Agents]);

  const [simModal, setSimModal] = useState(null);
  const [execAnim, setExecAnim] = useState(null);

  const handleUpload = useCallback(async (file) => {
    if (mock.isMock) {
      const id = mock.startMockPipeline();
      if (id) setJobId(id);
      return;
    }
    const id = await uploadAndStart(file);
    if (id) setJobId(id);
  }, [mock, uploadAndStart]);

  const handleExecuteItem = useCallback((itemId, platforms) => {
    const item = items.find(i => i.item_id === itemId);
    const listing = listings[itemId];
    if (item) {
      setExecAnim({ item, listing, platforms });
      executeItem(itemId, platforms);
    }
  }, [items, listings, executeItem]);

  const handleAnimComplete = useCallback(() => {
    setSimModal(execAnim);
    setExecAnim(null);
  }, [execAnim]);

  return (
    <div className="app">
      <motion.header
        className="topbar"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 2.4, ease: [0.32, 0.72, 0, 1] }}
      >
        <div className="topbar-brand">
          <ReRouteLogo size={28} />
          <span className="topbar-title">ReRoute</span>
          {mock.isMock && <span className="topbar-subtitle">MOCK MODE</span>}
        </div>
        <div className="topbar-controls">
          {agentSummary.total > 0 ? (
            <div className="topbar-agents">
              <Activity size={14} className={agentSummary.active > 0 ? 'agent-active-icon' : ''} />
              <span>
                {agentSummary.active > 0
                  ? `${agentSummary.active} agent${agentSummary.active !== 1 ? 's' : ''} working`
                  : `${agentSummary.done}/${agentSummary.total} complete`}
              </span>
            </div>
          ) : (
            <div className="topbar-auth">
              <motion.button
                className="topbar-btn topbar-btn-ghost"
                whileHover={{ scale: 1.04 }}
                whileTap={{ scale: 0.97 }}
                transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
              >
                Log in
              </motion.button>
              <motion.button
                className="topbar-btn topbar-btn-primary"
                whileHover={{ scale: 1.04 }}
                whileTap={{ scale: 0.97 }}
                transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
              >
                Sign up
              </motion.button>
            </div>
          )}
        </div>
      </motion.header>

      <AnimatePresence mode="wait">
        <Layout
          job={job}
          items={items}
          bids={bids}
          decisions={decisions}
          listings={listings}
          threads={threads}
          agents={agents}
          agentsRaw={agentsRaw}
          agentsByItem={agentsByItem}
          stage3Plan={stage3Plan}
          events={events}
          lastEvent={lastEvent}
          onUpload={handleUpload}
          onExecuteItem={handleExecuteItem}
          onSendReply={sendReply}
          v2Agents={v2Agents}
          pipelineStage={pipelineStage}
          send={send}
          screenshots={screenshots}
        />
      </AnimatePresence>

      <AnimatePresence>
        {execAnim && (
          <ExecuteRouteAnimation onComplete={handleAnimComplete} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {simModal && (
          <ListingSimulationModal
            item={simModal.item}
            listing={simModal.listing}
            onClose={() => setSimModal(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
