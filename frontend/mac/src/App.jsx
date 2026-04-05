import { useState, useCallback, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Cpu, Scale, Send, MessageSquare } from 'lucide-react';
import Layout from './components/Layout';
import SwarmaLogo from './components/SwarmaLogo';
import ListingSimulationModal from './components/modules/ListingSimulationModal';
import ExecuteRouteAnimation from './components/modules/ExecuteRouteAnimation';
import PostingWorkspace from './components/modules/PostingWorkspace';
import { useJob } from './hooks/useJob';
import { useScreenshots } from './hooks/useScreenshots';
import { useMockMode, getPostingDevMock } from './utils/mockData';

const STEPS = [
  { id: 'processing', label: 'Processing', icon: Cpu },
  { id: 'research', label: 'Research', icon: Scale },
  { id: 'posting', label: 'Posting', icon: Send },
  { id: 'concierge', label: 'Concierge', icon: MessageSquare },
];

function researchUnlocked(agents, items) {
  if ((items?.length ?? 0) > 0) return true;
  const st = agents?.intake?.status;
  return st === 'agent_completed' || st === 'done';
}

function TopbarSteps({
  pipelineStage,
  agents,
  items,
  v2Agents,
  screenshots,
  highlightIdx,
  onStepClick,
}) {
  const unlocked = researchUnlocked(agents, items);
  const effectiveIdx = highlightIdx;

  const listingAgents = useMemo(() => {
    return Object.values(v2Agents || {}).filter(a => a.phase === 'listing');
  }, [v2Agents]);
  const listingDone = listingAgents.length > 0 && listingAgents.every(
    a => a.status === 'complete' || a.status === 'error' || a.status === 'blocked'
  );

  // Research glow: every research agent has a screenshot frame in the frontend
  const researchReady = useMemo(() => {
    const research = Object.values(v2Agents || {}).filter(a => a.phase === 'research');
    if (research.length === 0) return false;
    if (!(screenshots instanceof Map)) return false;
    return research.every(a => screenshots.has(a.agent_id));
  }, [v2Agents, screenshots]);

  // Posting glow: every listing agent has a screenshot frame in the frontend
  const listingReady = useMemo(() => {
    if (listingAgents.length === 0) return false;
    if (!(screenshots instanceof Map)) return false;
    return listingAgents.every(a => screenshots.has(a.agent_id));
  }, [listingAgents, screenshots]);

  return (
    <div className="topbar-steps">
      {STEPS.map((step, i) => {
        const Icon = step.icon;
        const isCurrent = i === effectiveIdx;
        const isPast = i < effectiveIdx;
        const isFuture = i > effectiveIdx;
        const canProcessing = i === 0;
        const canResearch = i === 1 && unlocked;
        const canPosting = i === 2 && effectiveIdx >= 1;
        const canConcierge = i === 3 && (listingDone || effectiveIdx >= 2);
        const clickable = canProcessing || canResearch || canPosting || canConcierge;
        const isPulsing = (i === 1 && researchReady && effectiveIdx === 0)
          || (i === 2 && listingReady && effectiveIdx === 1)
          || (i === 3 && listingDone && effectiveIdx === 2);

        let cls = 'ts-node';
        if (isCurrent) cls += ' ts-current ts-clickable';
        else if (isPast) cls += ' ts-past ts-clickable';
        else if (i === 1 && unlocked) cls += ' ts-available ts-clickable';
        else if (i === 2 && effectiveIdx >= 1) cls += ' ts-available ts-clickable';
        else if (canConcierge) cls += ' ts-available ts-clickable';
        else cls += ' ts-future';
        if (isPulsing) cls += ' ts-pulsing';

        const activate = () => {
          if (canProcessing) onStepClick?.(0);
          else if (canResearch) onStepClick?.(1);
          else if (canPosting) onStepClick?.(2);
          else if (canConcierge) onStepClick?.(3);
        };

        return (
          <div key={step.id} className="topbar-step-group">
            {i > 0 && <div className={`ts-line ${effectiveIdx >= i ? 'ts-line-done' : ''}`} />}
            <div
              className={cls}
              role={clickable ? 'button' : undefined}
              tabIndex={clickable ? 0 : undefined}
              onClick={clickable ? activate : undefined}
              onKeyDown={
                clickable
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        activate();
                      }
                    }
                  : undefined
              }
            >
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

  const [simModal, setSimModal] = useState(null);
  const [execAnim, setExecAnim] = useState(null);
  const [topbarStepIdx, setTopbarStepIdx] = useState(0);
  const [theaterNavRequest, setTheaterNavRequest] = useState(null);

  useEffect(() => {
    setTopbarStepIdx(0);
    setTheaterNavRequest(null);
  }, [job?.job_id]);

  // Stage navigation is manual — user clicks topbar icons when they
  // pulse blue.  Browser-Use agents run autonomously; the blue signal
  // means the next page's data is loaded and ready to render.

  const handleTopbarStep = useCallback((groupIdx) => {
    setTopbarStepIdx(groupIdx);
    setTheaterNavRequest({ groupIdx, id: Date.now() });
  }, []);

  const handleTheaterStageFromPipeline = useCallback(() => {
    // no-op: topbar step only changes on direct topbar click (handleTopbarStep)
  }, []);

  const handleTheaterNavConsumed = useCallback(() => {
    setTheaterNavRequest(null);
  }, []);

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
            <span className="topbar-title">SwarmSell</span>
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
              <span className="topbar-title">SwarmSell</span>
              {mock.isMock && <span className="topbar-subtitle">MOCK MODE</span>}
            </div>
            <TopbarSteps
              pipelineStage={pipelineStage}
              agents={agents}
              items={items}
              v2Agents={v2Agents}
              screenshots={screenshots}
              highlightIdx={topbarStepIdx}
              onStepClick={handleTopbarStep}
            />
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
          theaterNavRequest={theaterNavRequest}
          onTheaterNavConsumed={handleTheaterNavConsumed}
          onTheaterStageChange={handleTheaterStageFromPipeline}
          topbarStepIdx={topbarStepIdx}
        />
      </AnimatePresence>

      <AnimatePresence>
        {topbarStepIdx >= 2 && execAnim && (
          <ExecuteRouteAnimation onComplete={handleAnimComplete} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {topbarStepIdx >= 2 && simModal && (
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
