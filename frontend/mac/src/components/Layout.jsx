import { useState, useMemo, useEffect } from 'react';
import { motion, AnimatePresence, LayoutGroup } from 'framer-motion';
import { Scan, Check, Loader2, ArrowLeft, ArrowRight } from 'lucide-react';
import IntakePanel from './panels/IntakePanel';
import AgentTheater from './panels/AgentTheater';
import DecisionPanel from './panels/DecisionPanel';
import SwarmGrid from './SwarmGrid';
import FocusMode from './FocusMode';
import { ACTIVE_STATUSES } from '../utils/contracts';

const EASE = [0.32, 0.72, 0, 1];

function getGlobalStage(agents, v2Agents, pipelineStage) {
  if (pipelineStage) return pipelineStage;

  const v2Entries = Object.values(v2Agents || {});
  if (v2Entries.length > 0) {
    const hasActive = v2Entries.some((a) => ACTIVE_STATUSES.has(a.status));
    const allComplete = v2Entries.every((a) => a.status === 'complete' || a.status === 'error');
    if (allComplete) return 'concierge-done';
    if (hasActive) return 'bidding';
  }

  const s = (id) => {
    const v = agents[id]?.status;
    if (v === 'agent_started' || v === 'thinking' || v === 'agent_progress') return 'thinking';
    if (v === 'agent_completed' || v === 'done') return 'done';
    return 'idle';
  };
  if (s('concierge') === 'done') return 'concierge-done';
  if (s('concierge') === 'thinking') return 'concierge';
  if (s('route_decider') === 'done' || s('route_decider') === 'thinking') return 'deciding';
  const routeAgents = ['marketplace_resale', 'trade_in', 'return', 'repair_roi'];
  if (routeAgents.some((a) => s(a) === 'thinking' || s(a) === 'done')) return 'bidding';
  if (s('condition_fusion') === 'done' || s('condition_fusion') === 'thinking') return 'processing';
  if (s('intake') === 'done' || s('intake') === 'thinking') return 'processing';
  return 'idle';
}

function MiniPlayer({ videoUrl, items, globalStage }) {
  const hasItems = items.length > 0;
  const isProcessing = globalStage === 'processing';

  return (
    <div className="mp-wrap">
      <motion.div className="mp-frame" layoutId="video-player" transition={{ duration: 0.6, ease: EASE }}>
        <video src={videoUrl} muted autoPlay loop playsInline />
        {isProcessing && !hasItems && <div className="mp-scanline" />}
        <div className="mp-overlay">
          <div className="mp-status">
            {hasItems ? (
              <><Check size={11} className="mp-icon-done" /><span>{items.length} found</span></>
            ) : (
              <><Loader2 size={11} className="mp-spinner" /><span>Analyzing...</span></>
            )}
          </div>
          <div className="mp-badge"><Scan size={10} /><span>LIVE</span></div>
        </div>
      </motion.div>
    </div>
  );
}

export default function Layout({
  job, items, bids, decisions, listings, threads, agents,
  agentsRaw, agentsByItem, stage3Plan, events, lastEvent,
  onUpload, onExecuteItem, onSendReply,
  v2Agents = {}, pipelineStage, send, screenshots,
}) {
  const [phase, setPhase] = useState('intake');
  const [videoUrl, setVideoUrl] = useState(null);
  const [focusedAgentId, setFocusedAgentId] = useState(null);

  useEffect(() => {
    return () => { if (videoUrl) URL.revokeObjectURL(videoUrl); };
  }, [videoUrl]);

  const globalStage = useMemo(
    () => getGlobalStage(agents, v2Agents, pipelineStage),
    [agents, v2Agents, pipelineStage],
  );
  const useV2 = Object.keys(v2Agents).length > 0;

  const [viewOverride, setViewOverride] = useState(null);
  const activeView = viewOverride || globalStage;

  useEffect(() => {
    if (viewOverride && viewOverride === globalStage) setViewOverride(null);
  }, [globalStage, viewOverride]);

  const showConciergeResults = activeView === 'concierge-done' || activeView === 'concierge';

  const handleUpload = (file, url) => {
    setVideoUrl(url);
    setPhase('processing');
    onUpload(file);
  };

  const focusedAgent = focusedAgentId ? v2Agents[focusedAgentId] : null;
  const focusedShot = focusedAgentId && screenshots
    ? (screenshots instanceof Map ? screenshots.get(focusedAgentId) : screenshots[focusedAgentId])
    : null;

  return (
    <LayoutGroup>
      <motion.div
        className="layout layout-unified"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, ease: EASE }}
      >
        <AnimatePresence mode="sync">
          {/* ── Phase: Intake ───────────────────────────────── */}
          {phase === 'intake' && (
            <motion.div
              key="intake-full"
              className="intake-fullscreen"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{
                opacity: 0,
                filter: 'blur(4px)',
                transition: { duration: 0.4, ease: EASE },
              }}
              transition={{ duration: 0.3, ease: EASE }}
            >
              <IntakePanel
                job={job}
                items={items}
                onUpload={handleUpload}
                fullscreen
              />
            </motion.div>
          )}

          {/* ── Phase: Processing ───────────────────────────── */}
          {phase === 'processing' && !showConciergeResults && (
            <motion.div
              key="processing"
              className="proc-layout"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, transition: { duration: 0.3 } }}
              transition={{ duration: 0.35, ease: EASE }}
            >
              {viewOverride && (globalStage === 'concierge-done' || globalStage === 'concierge') && (
                <motion.button
                  className="view-override-banner"
                  onClick={() => setViewOverride(null)}
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, ease: EASE }}
                >
                  <span>Results are ready</span>
                  <ArrowRight size={14} />
                  <span>View Decisions</span>
                </motion.button>
              )}

              <motion.div
                className="proc-pipeline"
                initial={{ opacity: 0, y: -16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, delay: 0.05, ease: EASE }}
              >
                <AgentTheater
                  job={job} items={items} bids={bids} decisions={decisions}
                  listings={listings} threads={threads} agents={agents}
                  agentsRaw={agentsRaw} agentsByItem={agentsByItem}
                  stage3Plan={stage3Plan} events={events} lastEvent={lastEvent}
                  onExecuteItem={onExecuteItem} onSendReply={onSendReply}
                  v2Agents={v2Agents} pipelineStage={pipelineStage} send={send}
                  miniPlayer={videoUrl ? (
                    <MiniPlayer videoUrl={videoUrl} items={items} globalStage={globalStage} />
                  ) : null}
                />
              </motion.div>

              {useV2 && Object.keys(v2Agents).length > 0 && (
                <motion.div
                  className="proc-swarm"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: 0.4, ease: EASE }}
                >
                  <SwarmGrid
                    v2Agents={v2Agents}
                    screenshots={screenshots}
                    onFocusAgent={setFocusedAgentId}
                    focusedAgentId={focusedAgentId}
                  />
                </motion.div>
              )}
            </motion.div>
          )}

          {/* ── Phase: Concierge Results ────────────────────── */}
          {phase === 'processing' && showConciergeResults && (
            <motion.div
              key="concierge-results"
              className="concierge-fullscreen"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.2 } }}
              transition={{ duration: 0.4, ease: EASE }}
            >
              <button className="back-to-pipeline-btn" onClick={() => setViewOverride('bidding')}>
                <ArrowLeft size={14} />
                <span>Back to Pipeline</span>
              </button>
              <DecisionPanel
                items={items} decisions={decisions} agents={agents}
                onExecuteItem={onExecuteItem} fullscreen
              />
            </motion.div>
          )}
        </AnimatePresence>

        <FocusMode
          agent={focusedAgent}
          screenshotUrl={focusedShot?.url}
          onClose={() => setFocusedAgentId(null)}
          send={send}
        />
      </motion.div>
    </LayoutGroup>
  );
}
