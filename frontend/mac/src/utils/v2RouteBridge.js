/**
 * Maps stub / v2 per-platform research agents (ebay-research-abc123, …) into the
 * four research-stage slots MissionControl expects: marketplace_resale, trade_in,
 * return, repair_roi.
 */

const SLOT_PLATFORMS = {
  marketplace_resale: ['facebook', 'depop'],
  trade_in: [],
  return: ['amazon'],
  repair_roi: [],
};

const ACTIVE_V2 = new Set(['queued', 'running', 'navigating', 'filling']);

const SLOT_LABELS = {
  marketplace_resale: 'Resale',
  trade_in: 'Trade-in',
  return: 'Return',
  repair_roi: 'Repair',
};

export function normalizeV2AgentsMap(agents) {
  if (!agents || typeof agents !== 'object') return {};
  const next = {};
  for (const [id, st] of Object.entries(agents)) {
    const base = st && typeof st === 'object' ? st : {};
    next[id] = {
      started_at: null,
      completed_at: null,
      error: null,
      result: null,
      ...base,
      agent_id: base.agent_id ?? base.agentId ?? id,
      status: base.status || 'queued',
    };
  }
  return next;
}

function mergeSlotStates(states, fallbackTask) {
  if (!states.length) return null;
  const task =
    states.map((s) => s.task).find(Boolean) || fallbackTask || 'Research…';
  if (states.some((s) => s.status === 'error')) {
    return { status: 'error', message: 'Agent error', task };
  }
  if (states.some((s) => ACTIVE_V2.has(s.status))) {
    return { status: 'thinking', message: task, task };
  }
  if (states.every((s) => s.status === 'complete')) {
    return { status: 'done', message: 'Complete', task };
  }
  return { status: 'thinking', message: task, task };
}

/**
 * @param {Record<string, object>} v2Agents
 * @param {Array<{ item_id?: string }>} items
 * @returns {Record<string, Record<string, { status, message?, task? }>>}
 */
export function buildV2RouteAgentsRaw(v2Agents, items) {
  const raw = {};
  if (!v2Agents || typeof v2Agents !== 'object' || !items?.length) return raw;

  for (const item of items) {
    const itemId = item?.item_id;
    if (!itemId) continue;
    const pref = itemId.slice(0, 6);

    for (const [slot, platforms] of Object.entries(SLOT_PLATFORMS)) {
      const collected = [];
      for (const p of platforms) {
        const key = `${p}-research-${pref}`;
        if (v2Agents[key]) collected.push(v2Agents[key]);
      }
      const merged = mergeSlotStates(
        collected,
        `${SLOT_LABELS[slot] || slot} research`,
      );
      if (!merged) continue;
      if (!raw[slot]) raw[slot] = {};
      raw[slot][itemId] = merged;
    }
  }
  return raw;
}
