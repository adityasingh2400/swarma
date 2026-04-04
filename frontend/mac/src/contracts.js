export const AGENT_EVENT_TYPES = [
  'agent:spawn',
  'agent:status',
  'agent:result',
  'agent:complete',
  'agent:error',
  'pipeline:update',
];

export const PIPELINE_STAGES = ['video', 'analysis', 'research', 'decision', 'listing'];

export const SCREENSHOT_FRAME_VERSION = 0x01;
export const SCREENSHOT_AGENT_ID_BYTES = 32;
export const SCREENSHOT_TIMESTAMP_BYTES = 4;
export const SCREENSHOT_HEADER_BYTES =
  1 + SCREENSHOT_AGENT_ID_BYTES + SCREENSHOT_TIMESTAMP_BYTES;
