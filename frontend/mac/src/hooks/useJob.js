import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useWebSocket } from './useWebSocket';
import { uploadVideo, getJobState } from '../utils/api';

const STATUS_PRIORITY = { thinking: 3, error: 2, done: 1 };

function aggregateAgents(raw) {
  const result = {};
  for (const [agentName, itemMap] of Object.entries(raw)) {
    let best = null, bestP = -1;
    for (const state of Object.values(itemMap)) {
      const p = STATUS_PRIORITY[state.status] ?? 0;
      if (p > bestP) { best = state; bestP = p; }
    }
    if (best) result[agentName] = best;
  }
  return result;
}

const AGENT_PLATFORM_MAP = {
  intake: 'analysis',
  condition_fusion: 'analysis',
  marketplace_resale: 'ebay',
  trade_in: 'trade-in',
  repair_roi: 'repair',
  return: 'return',
  route_decider: 'decision',
};

const AGENT_PHASE_MAP = {
  intake: 'research',
  condition_fusion: 'research',
  marketplace_resale: 'research',
  trade_in: 'research',
  repair_roi: 'research',
  return: 'research',
  route_decider: 'listing',
};

const MOCK_PLATFORMS = ['ebay', 'facebook', 'mercari', 'depop'];
const MOCK_STATUSES = ['queued', 'running', 'navigating', 'filling', 'complete', 'error'];

function buildMockAgents() {
  const out = {};
  for (let i = 0; i < 12; i++) {
    const plat = MOCK_PLATFORMS[i % MOCK_PLATFORMS.length];
    const phase = i < 6 ? 'research' : 'listing';
    const st = MOCK_STATUSES[i % MOCK_STATUSES.length];
    const id = `${plat}-${phase}-${i}`;
    out[id] = {
      agent_id: id,
      item_id: `item-${Math.floor(i / 4)}`,
      platform: plat,
      phase,
      status: st,
      task: `${phase === 'research' ? 'Search' : 'Post to'} ${plat} for item ${Math.floor(i / 4)}`,
      started_at: Date.now() / 1000 - Math.random() * 60,
      completed_at: st === 'complete' ? Date.now() / 1000 : null,
      result: null,
      error: st === 'error' ? 'Agent timeout' : null,
    };
  }
  return out;
}

function inferPipelineStage(v2) {
  const list = Object.values(v2);
  if (list.length === 0) return 'video';
  const hasListing = list.some((a) => a.phase === 'listing');
  const allDone = list.every((a) => a.status === 'complete' || a.status === 'error');
  if (hasListing && allDone) return 'listing';
  if (hasListing) return 'listing';
  const hasResearch = list.some((a) => a.phase === 'research');
  if (hasResearch) return 'research';
  return 'analysis';
}

function computePipelineStats(v2) {
  const list = Object.values(v2);
  const research = list.filter((a) => a.phase === 'research');
  const listing = list.filter((a) => a.phase === 'listing');
  return {
    researchTotal: research.length,
    researchDone: research.filter((a) => a.status === 'complete').length,
    listingTotal: listing.length,
    listingDone: listing.filter((a) => a.status === 'complete').length,
  };
}

export function useJob(jobId) {
  const [job, setJob] = useState(null);
  const [items, setItems] = useState([]);
  const [v2Agents, setV2Agents] = useState({});
  const [agentsRaw, setAgentsRaw] = useState({});
  const agents = useMemo(() => aggregateAgents(agentsRaw), [agentsRaw]);

  const { connected, subscribe, send } = useWebSocket(jobId);
  const initialized = useRef(false);
  const isMock = useRef(false);

  useEffect(() => {
    if (!jobId) return;
    if (jobId === 'mock-demo') {
      isMock.current = true;
      setV2Agents(buildMockAgents());
      setItems([
        { item_id: 'item-0', name: 'iPhone 15 Pro', confidence: 0.94 },
        { item_id: 'item-1', name: 'MacBook Air M2', confidence: 0.88 },
        { item_id: 'item-2', name: 'AirPods Pro', confidence: 0.91 },
      ]);
      return;
    }
    if (initialized.current) return;
    initialized.current = true;

    getJobState(jobId)
      .then((state) => {
        if (state.job) setJob(state.job);
        if (state.items) setItems(state.items);
        if (state.agent_states_raw) {
          setAgentsRaw(state.agent_states_raw);
        }
      })
      .catch(() => {});
  }, [jobId]);

  useEffect(() => {
    if (isMock.current) return;
    return subscribe((event) => {
      const { type, data } = event;
      if (!type || !data) return;

      switch (type) {
        case 'initial_state':
          if (data.job) setJob(data.job);
          if (data.items) setItems(data.items);
          if (data.agent_states_raw) setAgentsRaw(data.agent_states_raw);
          break;

        case 'job_created':
        case 'job_updated':
          setJob((prev) => ({ ...prev, ...data }));
          break;

        case 'item_added':
          setItems((prev) => {
            const idx = prev.findIndex((i) => i.item_id === data.item_id);
            return idx >= 0
              ? prev.map((i, j) => (j === idx ? { ...i, ...data } : i))
              : [...prev, data];
          });
          break;

        case 'item:identified':
          setItems((prev) => {
            const idx = prev.findIndex((i) => i.item_id === data.itemId);
            const item = { item_id: data.itemId, name: data.name, confidence: data.confidence };
            return idx >= 0
              ? prev.map((i, j) => (j === idx ? { ...i, ...item } : i))
              : [...prev, item];
          });
          break;

        case 'agent:spawn':
          setV2Agents((prev) => ({
            ...prev,
            [data.agentId]: {
              agent_id: data.agentId,
              platform: data.platform,
              phase: data.phase,
              status: 'queued',
              task: data.task,
              started_at: Date.now() / 1000,
              completed_at: null,
              result: null,
              error: null,
            },
          }));
          break;

        case 'agent:status':
          setV2Agents((prev) => {
            const existing = prev[data.agentId];
            if (!existing) return prev;
            return {
              ...prev,
              [data.agentId]: { ...existing, status: data.status, task: data.detail || existing.task },
            };
          });
          break;

        case 'agent:result':
          setV2Agents((prev) => {
            const existing = prev[data.agentId];
            if (!existing) return prev;
            return {
              ...prev,
              [data.agentId]: { ...existing, result: data.data },
            };
          });
          break;

        case 'agent:complete':
          setV2Agents((prev) => {
            const existing = prev[data.agentId];
            if (!existing) return prev;
            return {
              ...prev,
              [data.agentId]: {
                ...existing,
                status: 'complete',
                completed_at: Date.now() / 1000,
              },
            };
          });
          break;

        case 'agent:error':
          setV2Agents((prev) => {
            const existing = prev[data.agentId];
            if (!existing) return prev;
            return {
              ...prev,
              [data.agentId]: {
                ...existing,
                status: 'error',
                error: data.error || 'Unknown error',
              },
            };
          });
          break;

        case 'pipeline:update':
          break;

        case 'agent_started': {
          const itemId = data.item_id || '_global';
          setAgentsRaw((prev) => ({
            ...prev,
            [data.agent]: {
              ...prev[data.agent],
              [itemId]: { status: 'thinking', message: data.message, progress: 0, item_id: data.item_id },
            },
          }));
          const v1Key = data.item_id ? `${data.agent}-${data.item_id}` : data.agent;
          setV2Agents((prev) => ({
            ...prev,
            [v1Key]: {
              agent_id: v1Key,
              platform: AGENT_PLATFORM_MAP[data.agent] || data.agent,
              phase: AGENT_PHASE_MAP[data.agent] || 'research',
              status: 'running',
              task: data.message || `${data.agent} working...`,
              item_id: data.item_id,
              item_name: data.item_name,
              started_at: Date.now() / 1000,
              completed_at: null,
              result: null,
              error: null,
            },
          }));
          break;
        }

        case 'agent_progress': {
          const pItemId = data.item_id || '_global';
          setAgentsRaw((prev) => {
            const existing = prev[data.agent]?.[pItemId] || {};
            return {
              ...prev,
              [data.agent]: {
                ...prev[data.agent],
                [pItemId]: { ...existing, message: data.message, progress: data.progress },
              },
            };
          });
          const pKey = data.item_id ? `${data.agent}-${data.item_id}` : data.agent;
          setV2Agents((prev) => {
            const ex = prev[pKey];
            if (!ex) return prev;
            return { ...prev, [pKey]: { ...ex, status: 'navigating', task: data.message || ex.task } };
          });
          break;
        }

        case 'agent_completed': {
          const cItemId = data.item_id || '_global';
          setAgentsRaw((prev) => {
            const existing = prev[data.agent]?.[cItemId] || {};
            return {
              ...prev,
              [data.agent]: {
                ...prev[data.agent],
                [cItemId]: { ...existing, status: 'done', message: data.message },
              },
            };
          });
          const cKey = data.item_id ? `${data.agent}-${data.item_id}` : data.agent;
          setV2Agents((prev) => {
            const ex = prev[cKey];
            if (!ex) return prev;
            return { ...prev, [cKey]: { ...ex, status: 'complete', completed_at: Date.now() / 1000, task: data.message || ex.task } };
          });
          break;
        }

        case 'agent_error': {
          const eItemId = data.item_id || '_global';
          setAgentsRaw((prev) => ({
            ...prev,
            [data.agent]: {
              ...prev[data.agent],
              [eItemId]: { status: 'error', message: data.error || data.message },
            },
          }));
          const eKey = data.item_id ? `${data.agent}-${data.item_id}` : data.agent;
          setV2Agents((prev) => {
            const ex = prev[eKey];
            if (!ex) return prev;
            return { ...prev, [eKey]: { ...ex, status: 'error', error: data.error || data.message } };
          });
          break;
        }
      }
    });
  }, [subscribe]);

  useEffect(() => {
    if (jobId) initialized.current = false;
  }, [jobId]);

  const pipelineStage = useMemo(() => inferPipelineStage(v2Agents), [v2Agents]);
  const pipelineStats = useMemo(() => computePipelineStats(v2Agents), [v2Agents]);

  const uploadAndStart = useCallback(async (file) => {
    try {
      const result = await uploadVideo(file);
      if (result?.job_id) {
        setJob({ job_id: result.job_id, status: result.status });
        return result.job_id;
      }
    } catch (err) {
      console.error('Upload failed:', err);
    }
    return null;
  }, []);

  const sendWs = useCallback(
    (payload) => send?.(payload),
    [send],
  );

  return {
    job,
    items,
    agents,
    v2Agents,
    pipelineStage,
    pipelineStats,
    connected,
    uploadAndStart,
    sendWs,
  };
}
