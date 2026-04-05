// ── Binary Screenshot Protocol ──────────────────────────────────────
export const SCREENSHOT_FRAME_VERSION = 0x01;
export const SCREENSHOT_AGENT_ID_BYTES = 32;
export const SCREENSHOT_TIMESTAMP_BYTES = 4;
export const SCREENSHOT_HEADER_BYTES =
  1 + SCREENSHOT_AGENT_ID_BYTES + SCREENSHOT_TIMESTAMP_BYTES; // 37

// ── WebSocket Event Types (Server → Client) ────────────────────────
export const EVENT_AGENT_SPAWN = 'agent:spawn';
export const EVENT_AGENT_STATUS = 'agent:status';
export const EVENT_AGENT_ERROR = 'agent:error';
export const EVENT_AGENT_COMPLETE = 'agent:complete';
export const EVENT_AGENT_RESULT = 'agent:result';
export const EVENT_ITEM_IDENTIFIED = 'item:identified';
export const EVENT_STATE_SNAPSHOT = 'state:snapshot';
export const EVENT_JOB_PROGRESS = 'job:progress';
export const EVENT_PIPELINE_UPDATE = 'pipeline:update';

// ── WebSocket Event Types (Client → Server) ────────────────────────
export const CMD_FOCUS_REQUEST = 'focus:request';
export const CMD_FOCUS_RELEASE = 'focus:release';

// ── v2 Agent Statuses ──────────────────────────────────────────────
export const STATUS_QUEUED = 'queued';
export const STATUS_RUNNING = 'running';
export const STATUS_NAVIGATING = 'navigating';
export const STATUS_FILLING = 'filling';
export const STATUS_COMPLETE = 'complete';
export const STATUS_ERROR = 'error';
export const STATUS_BLOCKED = 'blocked';

export const ACTIVE_STATUSES = new Set([
  STATUS_QUEUED,
  STATUS_RUNNING,
  STATUS_NAVIGATING,
  STATUS_FILLING,
]);

export const TERMINAL_STATUSES = new Set([
  STATUS_COMPLETE,
  STATUS_ERROR,
  STATUS_BLOCKED,
]);

// ── v2 Agent Phases ────────────────────────────────────────────────
export const PHASE_RESEARCH = 'research';
export const PHASE_LISTING = 'listing';

// ── Platform IDs ───────────────────────────────────────────────────
export const PLATFORMS = ['ebay', 'facebook', 'mercari', 'depop'];
