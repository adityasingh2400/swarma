import { createContext, useContext, useRef, useEffect, useCallback } from 'react';

const GRID_COLS = 4;
const GRID_ROWS = 3;
const GRID_SLOTS = GRID_COLS * GRID_ROWS;
const THROTTLE_MS = 66;
const ACTIVE_STATUSES = new Set(['running', 'navigating', 'filling']);
const FRESHNESS_MAX_AGE = 5000;

function defaultSlots() {
  return Array.from({ length: GRID_SLOTS }, (_, i) => ({
    id: `slot-${i}`,
    status: 'placeholder',
    platform: '',
    phase: '',
    freshness: 0,
    gridIndex: i,
    normalizedXY: [
      ((i % GRID_COLS) + 0.5) / GRID_COLS,
      (Math.floor(i / GRID_COLS) + 0.5) / GRID_ROWS,
    ],
  }));
}

const SwarmActivityContext = createContext(null);

export function useSwarmActivity() {
  return useContext(SwarmActivityContext);
}

export default function SwarmActivityProvider({
  v2Agents,
  pipelineStage,
  getScreenshotMeta,
  focusedAgentId,
  children,
}) {
  const metricsRef = useRef({
    agents: defaultSlots(),
    pipelineStage: 'video',
    activeCount: 0,
    byteRate: 0,
    focusedAgentId: null,
  });

  const frameTimesRef = useRef([]);
  const lastEmitRef = useRef(0);

  const computeMetrics = useCallback(() => {
    const now = Date.now();
    const agentList = Object.values(v2Agents || {}).filter(
      (a) => a && a.agent_id,
    );

    const agents = [];
    let activeCount = 0;

    for (let i = 0; i < GRID_SLOTS; i++) {
      const a = agentList[i];
      if (a) {
        const meta = getScreenshotMeta?.(a.agent_id);
        const age = meta ? now - meta.updatedAt : FRESHNESS_MAX_AGE;
        const freshness = Math.max(0, 1 - age / FRESHNESS_MAX_AGE);
        if (ACTIVE_STATUSES.has(a.status)) activeCount++;

        if (meta) {
          frameTimesRef.current.push(now);
        }

        agents.push({
          id: a.agent_id,
          status: a.status || 'queued',
          platform: a.platform || '',
          phase: a.phase || 'research',
          freshness,
          gridIndex: i,
          normalizedXY: [
            ((i % GRID_COLS) + 0.5) / GRID_COLS,
            (Math.floor(i / GRID_COLS) + 0.5) / GRID_ROWS,
          ],
        });
      } else {
        agents.push({
          id: `slot-${i}`,
          status: 'placeholder',
          platform: '',
          phase: '',
          freshness: 0,
          gridIndex: i,
          normalizedXY: [
            ((i % GRID_COLS) + 0.5) / GRID_COLS,
            (Math.floor(i / GRID_COLS) + 0.5) / GRID_ROWS,
          ],
        });
      }
    }

    const cutoff = now - 2000;
    frameTimesRef.current = frameTimesRef.current.filter((t) => t > cutoff);
    const framesPerSec = frameTimesRef.current.length / 2;
    const byteRate = framesPerSec * 20000;

    metricsRef.current = {
      agents,
      pipelineStage: pipelineStage || 'video',
      activeCount,
      byteRate,
      focusedAgentId: focusedAgentId || null,
    };
  }, [v2Agents, pipelineStage, getScreenshotMeta, focusedAgentId]);

  useEffect(() => {
    let rafId;
    function tick() {
      const now = performance.now();
      if (now - lastEmitRef.current >= THROTTLE_MS) {
        lastEmitRef.current = now;
        computeMetrics();
      }
      rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [computeMetrics]);

  return (
    <SwarmActivityContext.Provider value={metricsRef}>
      {children}
    </SwarmActivityContext.Provider>
  );
}
