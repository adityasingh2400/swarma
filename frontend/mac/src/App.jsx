import { useState, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Cpu, Scale, Send, MessageSquare } from 'lucide-react';
import Layout from './components/Layout';
import SwarmaLogo from './components/SwarmaLogo';
import ListingSimulationModal from './components/modules/ListingSimulationModal';
import ExecuteRouteAnimation from './components/modules/ExecuteRouteAnimation';
import PostingWorkspace from './components/modules/PostingWorkspace';
import { useJob } from './hooks/useJob';
import { useScreenshots } from './hooks/useScreenshots';
import { useMockMode, getPostingDevMock } from './utils/mockData';
import { ACTIVE_STATUSES } from './utils/contracts';

const STEPS = [
  { id: 'processing', label: 'Processing', icon: Cpu },
  { id: 'bidding', label: 'Route Bidding', icon: Scale },
  { id: 'posting', label: 'Posting', icon: Send },
  { id: 'concierge', label: 'Concierge', icon: MessageSquare },
];

function TopbarSteps({ pipelineStage }) {
  let activeIdx = 0;
  if (pipelineStage === 'executing') activeIdx = 1;

  return (
    <div className="topbar-steps">
      {STEPS.map((step, i) => {
        const Icon = step.icon;
        const isCurrent = i === activeIdx;
        const isPast = i < activeIdx;
        const cls = isCurrent ? 'ts-current' : isPast ? 'ts-past' : 'ts-future';
        return (
          <div key={step.id} className="topbar-step-group">
            {i > 0 && <div className={`ts-line ${isPast ? 'ts-line-done' : ''}`} />}
            <div className={`ts-node ${cls}`}>
              <Icon size={12} />
              <span>{step.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function App() {
  const postingDev = useMemo(() => {
    if (typeof window === 'undefined') return false;
    return new URLSearchParams(window.location.search).has('posting');
  }, []);

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
    postingStatus: realPostingStatus,
    send: realSend,
  } = useJob(mock.isMock ? null : jobId);

  const { screenshots: realScreenshots } = useScreenshots(mock.isMock ? null : jobId);

  const job = mock.isMock ? mock.job : realJob;
  const items = mock.isMock ? mock.items : realItems;
  const v2Agents = mock.isMock ? mock.v2Agents : realV2Agents;
  const pipelineStage = mock.isMock ? mock.pipelineStage : realPipelineStage;
  const postingStatus = mock.isMock ? {} : realPostingStatus;
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

  if (postingDev) {
    const { items: pdItems, decisions: pdDecisions } = getPostingDevMock();
    return (
      <div className="app posting-dev-app">
        <header className="topbar posting-dev-topbar">
          <div className="topbar-brand">
            <SwarmaLogo size={28} />
            <span className="topbar-title">Swarma</span>
            <span className="topbar-subtitle posting-dev-badge">Posting only · mock data</span>
          </div>
          <p className="posting-dev-hint">
            Remove <code>?posting</code> from the URL for the full app. Use <code>?mock</code> for the full mock pipeline.
          </p>
        </header>
        <main className="posting-dev-main">
          <PostingWorkspace items={pdItems} decisions={pdDecisions} initialStarted />
        </main>
      </div>
    );
  }

  return (
    <div className="app">
      <AnimatePresence>
        {job && (
          <motion.header
            className="topbar"
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.45, ease: [0.32, 0.72, 0, 1] }}
          >
            <div className="topbar-brand" onClick={() => { window.location.href = window.location.pathname; }} style={{ cursor: 'pointer' }}>
              <SwarmaLogo size={28} />
              <span className="topbar-title">Swarma</span>
              {mock.isMock && <span className="topbar-subtitle">MOCK MODE</span>}
            </div>
            <TopbarSteps pipelineStage={pipelineStage} />
            <div className="topbar-controls" />
          </motion.header>
        )}
      </AnimatePresence>

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
          postingStatus={postingStatus}
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
