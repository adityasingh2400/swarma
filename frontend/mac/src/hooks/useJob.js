import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useWebSocket } from './useWebSocket';
import { uploadVideo, getJobState, executeItem as execItem, sendReply as replyApi } from '../utils/api';
import { swarmaFe, summarizeWsEvent } from '../utils/debugLog';
import { buildV2RouteAgentsRaw, normalizeV2AgentsMap } from '../utils/v2RouteBridge';
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
  const agentsRawMerged = useMemo(() => {
    const patch = buildV2RouteAgentsRaw(v2Agents, items);
    const out = { ...agentsRaw };
    for (const [agentName, itemMap] of Object.entries(patch)) {
      out[agentName] = { ...(out[agentName] || {}), ...itemMap };
    }
    return out;
  }, [agentsRaw, v2Agents, items]);
  // Exposed: aggregated agent states (highest priority per agent)
  const agents = useMemo(() => aggregateAgents(agentsRawMerged), [agentsRawMerged]);
  // Exposed: item-centric view: { itemId: { agentName: state } }
  const agentsByItem = useMemo(() => {
    const result = {};
    for (const [agentName, itemMap] of Object.entries(agentsRawMerged)) {
      for (const [itemId, state] of Object.entries(itemMap)) {
        if (itemId === '_global') continue;
        if (!result[itemId]) result[itemId] = {};
        result[itemId][agentName] = state;
      }
    }
    return result;
  }, [agentsRawMerged]);

  const { connected, events, lastEvent, subscribe, send } = useWebSocket(jobId);
  const prevJobRef = useRef(null);

  useEffect(() => {
    if (!jobId || jobId === prevJobRef.current) return;
    prevJobRef.current = jobId;

    let stale = false;

    swarmaFe('useJob', 'rest_get_job_start', { jobId });
    getJobState(jobId)
      .then((state) => {
        if (stale) return;
        const jobPayload = state.job ?? state;
        swarmaFe('useJob', 'rest_get_job_ok', {
          jobId,
          hasJob: jobPayload?.job_id != null,
          jobStatus: jobPayload?.status,
          itemsN: state.items?.length ?? 0,
        });
        if (jobPayload?.job_id != null) setJob(jobPayload);
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
      .catch((err) => {
        swarmaFe('useJob', 'rest_get_job_error', { jobId, err: String(err) });
      });

    return () => { stale = true; };
  }, [jobId]);

  useEffect(() => {
    return subscribe((event) => {
      const { type, data } = event;
      swarmaFe('useJob', 'ws_dispatch', summarizeWsEvent(event));
      if (!type || !data) {
        swarmaFe('useJob', 'ws_skip_missing_type_or_data', { type, hasData: !!data });
        return;
      }

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
          if (data.agents && typeof data.agents === 'object') {
            setV2Agents(normalizeV2AgentsMap(data.agents));
          }
          break;

        case 'job_created':
        case 'job_updated':
          setJob((prev) => ({ ...prev, ...data }));
          if (data.status === 'executing') setPipelineStage('executing');
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
        case 'decision:made': {
          const prices = data.prices || {};
          const bestPlatform = Object.entries(prices).sort((a, b) => b[1] - a[1])[0];
          const bestValue = bestPlatform ? Math.round(bestPlatform[1]) : 0;
          setDecisions((prev) => ({
            ...prev,
            [data.item_id]: {
              ...data,
              best_route: 'sell_as_is',
              estimated_best_value: bestValue,
              route_reason: bestPlatform ? `Best return via ${bestPlatform[0]}` : '',
            },
          }));
          break;
        }

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
            const agentMap = {
              ...prev[data.agent],
              [itemId]: {
                ...existing,
                status: 'done',
                message: data.message,
                elapsed_ms: data.elapsed_ms,
                confidence: data.confidence,
                item_id: data.item_id,
                frame_paths: data.frame_paths ?? existing.frame_paths,
                transcript_text: data.transcript_text ?? existing.transcript_text,
                progress: data.progress ?? existing.progress,
              },
            };
            return { ...prev, [data.agent]: agentMap };
          });
          break;
        case 'agent:error':
        case 'agent_error':
          setAgentsRaw((prev) => {
            const agentKey = data.agent || data.agentId;
            if (!agentKey) return prev;
            const itemId = data.item_id || '_global';
            const agentMap = {
              ...prev[agentKey],
              [itemId]: {
                status: 'error',
                message: data.error || data.message,
                elapsed_ms: data.elapsed_ms,
                item_id: data.item_id,
              },
            };
            return { ...prev, [agentKey]: agentMap };
          });
          break;

        case EVENT_AGENT_SPAWN: {
          const aid = data.agent_id ?? data.agentId;
          if (!aid) break;
          setV2Agents((prev) => ({
            ...prev,
            [aid]: {
              started_at: null, completed_at: null, error: null, result: null,
              ...data,
              agent_id: aid,
              status: data.status || 'queued',
            },
          }));
          break;
        }
        case EVENT_AGENT_STATUS: {
          const aid = data.agent_id ?? data.agentId;
          if (!aid) break;
          setV2Agents((prev) => {
            const existing = prev[aid] || {};
            if (existing.status === 'complete' || existing.status === 'error') return prev;
            return { ...prev, [aid]: { ...existing, ...data, agent_id: aid } };
          });
          break;
        }
        case EVENT_AGENT_ERROR: {
          const aid = data.agent_id ?? data.agentId;
          if (!aid) break;
          setV2Agents((prev) => {
            const existing = prev[aid] || {};
            return { ...prev, [aid]: { ...existing, ...data, agent_id: aid, status: 'error' } };
          });
          break;
        }
        case EVENT_AGENT_COMPLETE: {
          const aid = data.agent_id ?? data.agentId;
          if (!aid) break;
          setV2Agents((prev) => {
            const existing = prev[aid] || {};
            return {
              ...prev,
              [aid]: {
                ...existing, ...data,
                agent_id: aid,
                status: 'complete',
                completed_at: data.completed_at || Date.now() / 1000,
              },
            };
          });
          break;
        }
        case EVENT_AGENT_RESULT: {
          const aid = data.agent_id ?? data.agentId;
          if (!aid) break;
          setV2Agents((prev) => {
            const existing = prev[aid] || {};
            return { ...prev, [aid]: { ...existing, result: data.result, agent_id: aid } };
          });
          break;
        }
        case EVENT_ITEM_IDENTIFIED:
          setItems((prev) => {
            const idx = prev.findIndex((i) => i.item_id === data.item_id);
            return idx >= 0
              ? prev.map((i, j) => (j === idx ? { ...i, ...data } : i))
              : [...prev, data];
          });
          break;
        case EVENT_STATE_SNAPSHOT:
          if (data.agents) setV2Agents(normalizeV2AgentsMap(data.agents));
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

        case 'concierge:started':
        case 'concierge:stopped':
        case 'concierge:message_received':
        case 'concierge:reply_sent':
          window.dispatchEvent(new CustomEvent('ws-event', {
            detail: { type, data },
          }));
          break;
      }
    });
  }, [subscribe]);

  const uploadAndStart = useCallback(async (file) => {
    swarmaFe('useJob', 'upload_start', {
      name: file?.name,
      size: file?.size,
      type: file?.type,
    });
    try {
      const result = await uploadVideo(file);
      if (result?.job_id) {
        swarmaFe('useJob', 'upload_http_ok', { job_id: result.job_id, status: result.status });
        setJob({ job_id: result.job_id, status: result.status });
        // Show intake progress strip immediately (before WS agent_started).
        setAgentsRaw((prev) => ({
          ...prev,
          intake: {
            ...(prev.intake || {}),
            _global: {
              status: 'thinking',
              message: 'Video uploaded — connecting and starting analysis…',
              progress: 0.03,
            },
          },
        }));
        return result.job_id;
      }
      swarmaFe('useJob', 'upload_http_no_job_id', { result });
    } catch (err) {
      console.error('Upload failed:', err);
      swarmaFe('useJob', 'upload_http_error', { err: String(err) });
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
    agentsRaw: agentsRawMerged,
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
