import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import IntakePanel from './panels/IntakePanel';
import PipelineHeader from './PipelineHeader';
import SwarmGrid from './SwarmGrid';
import FocusMode from './FocusMode';
import AuroraCanvas from './AuroraCanvas';
import SwarmActivityProvider from './SwarmActivityProvider';

export default function Layout({
  jobId,
  job,
  items,
  connected,
  v2Agents,
  pipelineStage,
  pipelineStats,
  getScreenshotUrl,
  getScreenshotMeta,
  sendWs,
  onUpload,
}) {
  const [focusedAgent, setFocusedAgent] = useState(null);

  const swarmSummary = useMemo(() => {
    const list = Object.values(v2Agents || {});
    const active = list.filter((a) =>
      ['running', 'navigating', 'filling', 'queued'].includes(a.status),
    ).length;
    const done = list.filter((a) =>
      ['complete', 'error', 'blocked'].includes(a.status),
    ).length;
    return { active, done, total: list.length };
  }, [v2Agents]);

  if (!jobId) {
    return (
      <SwarmActivityProvider
        v2Agents={{}}
        pipelineStage="video"
        getScreenshotMeta={getScreenshotMeta}
        focusedAgentId={null}
      >
        <div className="layout layout--intake">
          <AuroraCanvas />
          <motion.div
            className="layout__content"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4 }}
          >
            <IntakePanel job={job} items={items} onUpload={onUpload} fullscreen />
          </motion.div>
        </div>
      </SwarmActivityProvider>
    );
  }

  return (
    <SwarmActivityProvider
      v2Agents={v2Agents}
      pipelineStage={pipelineStage}
      getScreenshotMeta={getScreenshotMeta}
      focusedAgentId={focusedAgent?.agent_id || null}
    >
      <div className="layout layout--swarm">
        <AuroraCanvas />
        <div className="layout__content">
          <PipelineHeader
            stage={pipelineStage}
            pipelineStats={pipelineStats}
            itemCount={items.length}
            connected={connected}
            activeAgentCount={swarmSummary.active}
            totalAgentCount={swarmSummary.total}
          />
          <main className="layout__main">
            <SwarmGrid
              agents={v2Agents}
              getScreenshotUrl={getScreenshotUrl}
              onSelectAgent={setFocusedAgent}
              focusedAgentId={focusedAgent?.agent_id}
            />
          </main>
          <AnimatePresence>
            {focusedAgent && (
              <FocusMode
                key={focusedAgent.agent_id}
                agent={focusedAgent}
                onClose={() => setFocusedAgent(null)}
                getScreenshotUrl={getScreenshotUrl}
                sendWs={sendWs}
              />
            )}
          </AnimatePresence>
        </div>
      </div>
    </SwarmActivityProvider>
  );
}
