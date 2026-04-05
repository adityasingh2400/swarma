/**
 * Copy-paste friendly frontend traces (browser DevTools → Console).
 * Filter: SWARMA:fe
 */

const PREFIX = 'SWARMA:fe';

function ts() {
  return new Date().toISOString();
}

/** Truncate nested values for readable one-liners */
function shrink(obj, maxDepth = 2, maxLen = 500) {
  if (obj == null) return obj;
  if (typeof obj !== 'object') return obj;
  try {
    const s = JSON.stringify(obj, (k, v) => {
      if (typeof v === 'string' && v.length > 120) return `${v.slice(0, 120)}…(len=${v.length})`;
      if (Array.isArray(v) && v.length > 20) return [`…${v.length} items`];
      return v;
    });
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s;
  } catch {
    return String(obj).slice(0, maxLen);
  }
}

/**
 * @param {string} component e.g. useJob, useWebSocket, api
 * @param {string} event e.g. ws_open, upload_ok
 * @param {Record<string, unknown>} [fields]
 */
export function swarmaFe(component, event, fields = {}) {
  const parts = [PREFIX, ts(), component, event];
  if (fields && Object.keys(fields).length) {
    parts.push(shrink(fields));
  }
  console.info(parts.join(' | '));
}

export function summarizeWsEvent(event) {
  if (!event || typeof event !== 'object') return { raw: String(event) };
  const { type, data } = event;
  const out = { type };
  if (data && typeof data === 'object') {
    out.dataKeys = Object.keys(data);
    if (data.agent != null) out.agent = data.agent;
    if (data.message != null && typeof data.message === 'string') {
      out.message = data.message.length > 100 ? `${data.message.slice(0, 100)}…` : data.message;
    }
    if (data.progress != null) out.progress = data.progress;
    if (Array.isArray(data.frame_paths)) out.frame_paths_n = data.frame_paths.length;
    if (typeof data.transcript_text === 'string') out.transcript_len = data.transcript_text.length;
    if (data.item_id != null) out.item_id = data.item_id;
    if (data.error != null) out.error = String(data.error).slice(0, 200);
  }
  return out;
}
