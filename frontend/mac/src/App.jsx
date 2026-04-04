import { useState, useCallback } from 'react';
import { AnimatePresence } from 'framer-motion';
import Layout from './components/Layout';
import { useJob } from './hooks/useJob';
import { useScreenshots } from './hooks/useScreenshots';

export default function App() {
  const [jobId, setJobId] = useState(() => {
    const p = new URLSearchParams(window.location.search);
    return p.get('mock') === '1' ? 'mock-demo' : null;
  });

  const {
    job,
    items,
    connected,
    v2Agents,
    pipelineStage,
    pipelineStats,
    uploadAndStart,
    sendWs,
  } = useJob(jobId);

  const { getScreenshotUrl, getScreenshotMeta } = useScreenshots(jobId);

  const handleUpload = useCallback(
    async (file) => {
      const id = await uploadAndStart(file);
      if (id) setJobId(id);
    },
    [uploadAndStart],
  );

  return (
    <AnimatePresence mode="wait">
      <Layout
        key={jobId || 'intake'}
        jobId={jobId}
        job={job}
        items={items}
        connected={connected}
        v2Agents={v2Agents || {}}
        pipelineStage={pipelineStage || 'video'}
        pipelineStats={pipelineStats || {}}
        getScreenshotUrl={getScreenshotUrl}
        getScreenshotMeta={getScreenshotMeta}
        sendWs={sendWs}
        onUpload={handleUpload}
      />
    </AnimatePresence>
  );
}
