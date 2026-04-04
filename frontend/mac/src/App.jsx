import { useState, useCallback, useMemo } from 'react';
import { AnimatePresence } from 'framer-motion';
import { Wifi, WifiOff, Activity } from 'lucide-react';
import Layout from './components/Layout';
import ReRouteLogo from './components/ReRouteLogo';
import ListingSimulationModal from './components/modules/ListingSimulationModal';
import ExecuteRouteAnimation from './components/modules/ExecuteRouteAnimation';
import { useJob } from './hooks/useJob';

export default function App() {
  const [jobId, setJobId] = useState(null);

  const {
    job,
    items,
    bids,
    decisions,
    listings,
    threads,
    agents,
    agentsRaw,
    agentsByItem,
    stage3Plan,
    connected,
    events,
    lastEvent,
    uploadAndStart,
    executeItem,
    sendReply,
  } = useJob(jobId);

  const agentSummary = useMemo(() => {
    const entries = Object.values(agents);
    const active = entries.filter((a) => ['thinking', 'agent_started', 'agent_progress'].includes(a.status)).length;
    const done = entries.filter((a) => ['done', 'agent_completed'].includes(a.status)).length;
    const total = entries.length;
    return { active, done, total };
  }, [agents]);

  const [simModal, setSimModal] = useState(null);
  const [execAnim, setExecAnim] = useState(null);

  const handleUpload = useCallback(async (file) => {
    const id = await uploadAndStart(file);
    if (id) setJobId(id);
  }, [uploadAndStart]);

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
      <header className="topbar">
        <div className="topbar-brand">
          <ReRouteLogo size={28} />
          <span className="topbar-title">ReRoute</span>
        </div>
        <div className="topbar-controls">
          {agentSummary.total > 0 && (
            <div className="topbar-agents">
              <Activity size={14} className={agentSummary.active > 0 ? 'agent-active-icon' : ''} />
              <span>
                {agentSummary.active > 0
                  ? `${agentSummary.active} agent${agentSummary.active !== 1 ? 's' : ''} working`
                  : `${agentSummary.done}/${agentSummary.total} complete`}
              </span>
            </div>
          )}
          <div className="topbar-status">
            <span className={`status-dot ${connected ? '' : 'disconnected'}`} />
            {connected ? <Wifi size={14} /> : <WifiOff size={14} />}
            <span>{connected ? 'Live' : 'Offline'}</span>
          </div>
        </div>
      </header>

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
