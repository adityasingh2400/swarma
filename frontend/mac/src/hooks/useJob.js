import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useWebSocket } from './useWebSocket';
import { uploadVideo, getJobState, executeItem as execItem, sendReply as replyApi } from '../utils/api';
import {
  EVENT_AGENT_SPAWN, EVENT_AGENT_STATUS, EVENT_AGENT_ERROR,
  EVENT_AGENT_COMPLETE, EVENT_AGENT_RESULT, EVENT_ITEM_IDENTIFIED,
  EVENT_STATE_SNAPSHOT, EVENT_JOB_PROGRESS, EVENT_PIPELINE_UPDATE,
  EVENT_ITEM_POSTED,
} from '../utils/contracts';

// Priority-based aggregation mirroring backend store.py logic.
// For each agent, we track state per item_id and expose the highest-priority
// (most active) state. This prevents multi-item clobbering: if item-1 completes
// but item-2 is still thinking, the agent shows "thinking".
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

export function useJob(jobId) {
  const [job, setJob] = useState(null);
  const [items, setItems] = useState([]);
  const [bids, setBids] = useState({});
  const [decisions, setDecisions] = useState({});
  const [listings, setListings] = useState({});
  const [threads, setThreads] = useState([]);
  // Stage 3 plan: { itemId: { name, agents[], hero_frame, condition, confidence } }
  const [stage3Plan, setStage3Plan] = useState(null);
  const [v2Agents, setV2Agents] = useState({});
  const [pipelineStage, setPipelineStage] = useState(null);
  // { "item-1:ebay": { status, listing_url, timestamp }, ... }
  const [postingStatus, setPostingStatus] = useState({});
  // Internal: per-item agent states: { agentName: { itemId: state } }
  const [agentsRaw, setAgentsRaw] = useState({});
  // Exposed: aggregated agent states (highest priority per agent)
  const agents = useMemo(() => aggregateAgents(agentsRaw), [agentsRaw]);
  // Exposed: item-centric view: { itemId: { agentName: state } }
  const agentsByItem = useMemo(() => {
    const result = {};
    for (const [agentName, itemMap] of Object.entries(agentsRaw)) {
      for (const [itemId, state] of Object.entries(itemMap)) {
        if (itemId === '_global') continue;
        if (!result[itemId]) result[itemId] = {};
        result[itemId][agentName] = state;
      }
    }
    return result;
  }, [agentsRaw]);

  const { connected, events, lastEvent, subscribe, send } = useWebSocket(jobId);
  const prevJobRef = useRef(null);

  useEffect(() => {
    if (!jobId || jobId === prevJobRef.current) return;
    prevJobRef.current = jobId;

    let stale = false;

    getJobState(jobId)
      .then((state) => {
        if (stale) return;
        if (state.job) setJob(state.job);
        if (state.items) setItems(state.items);
        if (state.bids) setBids(state.bids || {});
        if (state.decisions) setDecisions(state.decisions || {});
        if (state.listings) setListings(state.listings || {});
        if (state.threads) {
          const flat = Object.values(state.threads || {}).flat();
          setThreads(flat);
        }
        if (state.agent_states_raw) {
          setAgentsRaw(state.agent_states_raw);
        } else if (state.agent_states) {
          const raw = {};
          for (const [agent, st] of Object.entries(state.agent_states)) {
            raw[agent] = { [st.item_id || '_global']: st };
          }
          setAgentsRaw(raw);
        }
      })
      .catch(() => {});

    return () => { stale = true; };
  }, [jobId]);

  useEffect(() => {
    return subscribe((event) => {
      const { type, data } = event;
      if (!type || !data) return;

      switch (type) {
        case 'initial_state':
          if (data.job) setJob(data.job);
          if (data.items) setItems(data.items);
          if (data.bids) setBids(data.bids || {});
          if (data.decisions) setDecisions(data.decisions || {});
          if (data.listings) setListings(data.listings || {});
          if (data.threads) {
            const flat = Object.values(data.threads || {}).flat();
            setThreads(flat);
          }
          if (data.agent_states_raw) {
            setAgentsRaw(data.agent_states_raw);
          } else if (data.agent_states) {
            const raw = {};
            for (const [agent, st] of Object.entries(data.agent_states)) {
              raw[agent] = { [st.item_id || '_global']: st };
            }
            setAgentsRaw(raw);
          }
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

        case 'bid_added':
          setBids((prev) => {
            const itemBids = [...(prev[data.item_id] || [])];
            const existingIdx = itemBids.findIndex((b) => b.route_type === data.route_type);
            if (existingIdx >= 0) {
              itemBids[existingIdx] = data;
            } else {
              itemBids.push(data);
            }
            return { ...prev, [data.item_id]: itemBids };
          });
          break;

        case 'comps_found':
          setBids((prev) => {
            const itemBids = [...(prev[data.item_id] || [])];
            const existingIdx = itemBids.findIndex((b) => b.route_type === 'sell_as_is');
            const newComps = data.comparables || [];
            if (existingIdx >= 0) {
              const existing = itemBids[existingIdx];
              const merged = [...(existing.comparable_listings || []), ...newComps];
              itemBids[existingIdx] = { ...existing, comparable_listings: merged, _streaming: true };
            } else {
              itemBids.push({
                route_type: 'sell_as_is', item_id: data.item_id,
                comparable_listings: newComps, viable: true, _streaming: true,
                estimated_value: 0, confidence: 0,
              });
            }
            return { ...prev, [data.item_id]: itemBids };
          });
          break;

        case 'decision_made':
          setDecisions((prev) => ({ ...prev, [data.item_id]: data }));
          break;

        case 'listing_updated':
          setListings((prev) => ({ ...prev, [data.item_id]: data }));
          break;

        case 'stage3_plan':
          setStage3Plan(data);
          break;

        case 'thread_updated':
          setThreads((prev) => {
            const idx = prev.findIndex((t) => t.thread_id === data.thread_id);
            return idx >= 0
              ? prev.map((t, j) => (j === idx ? { ...t, ...data } : t))
              : [...prev, data];
          });
          break;

        case 'agent_started':
          setAgentsRaw((prev) => {
            const itemId = data.item_id || '_global';
            const agentMap = { ...prev[data.agent], [itemId]: { status: 'thinking', message: data.message, progress: 0, item_id: data.item_id } };
            return { ...prev, [data.agent]: agentMap };
          });
          break;
        case 'agent_progress':
          setAgentsRaw((prev) => {
            const itemId = data.item_id || '_global';
            const existing = prev[data.agent]?.[itemId] || {};
            const agentMap = { ...prev[data.agent], [itemId]: {
              ...existing, message: data.message, confidence: data.confidence,
              progress: data.progress, frame_paths: data.frame_paths || existing.frame_paths,
              transcript_text: data.transcript_text || existing.transcript_text,
            } };
            return { ...prev, [data.agent]: agentMap };
          });
          break;
        case 'agent_completed':
          setAgentsRaw((prev) => {
            const itemId = data.item_id || '_global';
            const existing = prev[data.agent]?.[itemId] || {};
            const agentMap = { ...prev[data.agent], [itemId]: { ...existing, status: 'done', message: data.message, elapsed_ms: data.elapsed_ms, confidence: data.confidence, item_id: data.item_id } };
            return { ...prev, [data.agent]: agentMap };
          });
          break;
        case 'agent_error':
          setAgentsRaw((prev) => {
            const itemId = data.item_id || '_global';
            const agentMap = { ...prev[data.agent], [itemId]: { status: 'error', message: data.error || data.message, elapsed_ms: data.elapsed_ms, item_id: data.item_id } };
            return { ...prev, [data.agent]: agentMap };
          });
          break;

        case EVENT_AGENT_SPAWN:
          setV2Agents((prev) => ({
            ...prev,
            [data.agent_id]: {
              started_at: null, completed_at: null, error: null, result: null,
              ...data,
              status: data.status || 'queued',
            },
          }));
          break;
        case EVENT_AGENT_STATUS:
          setV2Agents((prev) => {
            const existing = prev[data.agent_id] || {};
            if (existing.status === 'complete' || existing.status === 'error') return prev;
            return { ...prev, [data.agent_id]: { ...existing, ...data } };
          });
          break;
        case EVENT_AGENT_ERROR:
          setV2Agents((prev) => {
            const existing = prev[data.agent_id] || {};
            return { ...prev, [data.agent_id]: { ...existing, ...data, status: 'error' } };
          });
          break;
        case EVENT_AGENT_COMPLETE:
          setV2Agents((prev) => {
            const existing = prev[data.agent_id] || {};
            return {
              ...prev,
              [data.agent_id]: {
                ...existing, ...data,
                status: 'complete',
                completed_at: data.completed_at || Date.now() / 1000,
              },
            };
          });
          break;
        case EVENT_AGENT_RESULT:
          setV2Agents((prev) => {
            const existing = prev[data.agent_id] || {};
            return { ...prev, [data.agent_id]: { ...existing, result: data.result } };
          });
          break;
        case EVENT_ITEM_IDENTIFIED:
          setItems((prev) => {
            const idx = prev.findIndex((i) => i.item_id === data.item_id);
            return idx >= 0
              ? prev.map((i, j) => (j === idx ? { ...i, ...data } : i))
              : [...prev, data];
          });
          break;
        case EVENT_STATE_SNAPSHOT:
          if (data.agents) setV2Agents(data.agents);
          if (data.items) setItems(data.items);
          if (data.pipeline_stage) setPipelineStage(data.pipeline_stage);
          break;
        case EVENT_JOB_PROGRESS:
          setJob((prev) => ({ ...prev, ...data }));
          break;
        case EVENT_PIPELINE_UPDATE:
          setPipelineStage(data.stage || data.pipeline_stage);
          break;
        case EVENT_ITEM_POSTED:
          setPostingStatus((prev) => ({
            ...prev,
            [`${data.item_id}:${data.platform}`]: {
              status: data.status,
              listing_url: data.listing_url || null,
              timestamp: data.timestamp || Date.now() / 1000,
            },
          }));
          break;
      }
    });
  }, [subscribe]);

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

  const executeItem = useCallback(async (itemId, platforms) => {
    if (!jobId) return;
    return execItem(jobId, itemId, platforms);
  }, [jobId]);

  const sendReply = useCallback(async (threadId, text) => {
    if (!jobId) return;
    return replyApi(jobId, threadId, text);
  }, [jobId]);

  return {
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
    v2Agents,
    pipelineStage,
    postingStatus,
    connected,
    events,
    lastEvent,
    uploadAndStart,
    executeItem,
    sendReply,
    send,
  };
}
