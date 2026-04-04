import { useState, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Scan, Check, Loader2, ArrowLeft, ArrowRight } from 'lucide-react';
import IntakePanel from './panels/IntakePanel';
import AgentTheater from './panels/AgentTheater';
import DecisionPanel from './panels/DecisionPanel';

function getGlobalStage(agents) {
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

function VideoFrame({ videoUrl, items, globalStage }) {
  const isProcessing = globalStage === 'processing';
  const hasItems = items.length > 0;

  return (
    <div className="vf-container">
      <div className="vf-frame">
        {/* Corner brackets */}
        <div className="vf-bracket vf-tl" />
        <div className="vf-bracket vf-tr" />
        <div className="vf-bracket vf-bl" />
        <div className="vf-bracket vf-br" />

        <video src={videoUrl} muted autoPlay loop playsInline />

        {/* Scan line animation */}
        {isProcessing && !hasItems && (
          <div className="vf-scanline" />
        )}

        {/* Bottom overlay bar */}
        <div className="vf-overlay">
          <div className="vf-status">
            {hasItems ? (
              <>
                <Check size={14} className="vf-status-icon done" />
                <span>{items.length} item{items.length !== 1 ? 's' : ''} found</span>
              </>
            ) : (
              <>
                <Loader2 size={14} className="vf-spinner" />
                <span>Analyzing video...</span>
              </>
            )}
          </div>
          <div className="vf-badge">
            <Scan size={12} />
            <span>LIVE</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Layout({
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
  events,
  lastEvent,
  onUpload,
  onExecuteItem,
  onSendReply,
}) {
  const [hasVideo, setHasVideo] = useState(false);
  const [videoUrl, setVideoUrl] = useState(null);
  const [videoSettled, setVideoSettled] = useState(false);
  const globalStage = useMemo(() => getGlobalStage(agents), [agents]);

  // Allow user to manually navigate back to pipeline from decision view
  const [viewOverride, setViewOverride] = useState(null);
  const activeView = viewOverride || globalStage;

  useEffect(() => {
    if (viewOverride && viewOverride === globalStage) {
      setViewOverride(null);
    }
  }, [globalStage, viewOverride]);

  const showVideo = hasVideo && !['bidding', 'deciding', 'concierge-done', 'concierge'].includes(activeView);
  const showCommandCenter = hasVideo && videoSettled;
  const showConciergeResults = activeView === 'concierge-done' || activeView === 'concierge';

  const handleUploadWithVideo = (file, url) => {
    setVideoUrl(url);
    setHasVideo(true);
    setTimeout(() => setVideoSettled(true), 900);
    onUpload(file);
  };

  return (
    <motion.div
      className="layout layout-unified"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <AnimatePresence mode="sync">
        {/* Full-screen intake when no video yet */}
        {!hasVideo && (
          <motion.div
            key="intake-full"
            className="intake-fullscreen"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.3 }}
          >
            <IntakePanel
              job={job}
              items={items}
              onUpload={handleUploadWithVideo}
              fullscreen
            />
          </motion.div>
        )}

        {/* Video starts centered, then slides to left third */}
        {hasVideo && showVideo && (
          <motion.div
            key="video-panel"
            className="video-panel"
            initial={{ left: '50%', x: '-50%', width: '400px' }}
            animate={{
              left: '0%',
              x: '0%',
              width: '33.333%',
            }}
            exit={{
              opacity: 0,
              x: '-100%',
              width: '0%',
            }}
            transition={{
              type: 'spring',
              stiffness: 120,
              damping: 22,
              delay: 0.1,
            }}
          >
            <VideoFrame videoUrl={videoUrl} items={items} globalStage={globalStage} />
          </motion.div>
        )}

        {/* Command center slides in after video settles */}
        {showCommandCenter && !showConciergeResults && (
          <motion.div
            key="command-center"
            className={`command-center ${!showVideo ? 'command-center-full' : ''}`}
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            transition={{ type: 'spring', stiffness: 160, damping: 24 }}
          >
            {viewOverride && (globalStage === 'concierge-done' || globalStage === 'concierge') && (
              <button className="view-override-banner" onClick={() => setViewOverride(null)}>
                <span>Results are ready</span>
                <ArrowRight size={14} />
                <span>View Decisions</span>
              </button>
            )}
            <AgentTheater
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
              onExecuteItem={onExecuteItem}
              onSendReply={onSendReply}
            />
          </motion.div>
        )}

        {/* Concierge final results */}
        {showConciergeResults && (
          <motion.div
            key="concierge-results"
            className="concierge-fullscreen"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ type: 'spring', stiffness: 180, damping: 24 }}
          >
            <button className="back-to-pipeline-btn" onClick={() => setViewOverride('bidding')}>
              <ArrowLeft size={14} />
              <span>Back to Pipeline</span>
            </button>
            <DecisionPanel
              items={items}
              decisions={decisions}
              agents={agents}
              onExecuteItem={onExecuteItem}
              fullscreen
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
