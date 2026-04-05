import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  STATUS_QUEUED, STATUS_RUNNING, STATUS_NAVIGATING, STATUS_FILLING,
  STATUS_COMPLETE, STATUS_ERROR,
  PHASE_RESEARCH, PHASE_LISTING,
  PLATFORMS,
} from './contracts';

const STATUS_SEQUENCE = [
  STATUS_QUEUED, STATUS_RUNNING, STATUS_NAVIGATING, STATUS_FILLING, STATUS_COMPLETE,
];

const MOCK_TASKS = {
  ebay: {
    research: 'Searching eBay sold listings for iPhone 15 Pro 256GB',
    listing: 'Listing item on eBay — filling title, condition, price',
  },
  facebook: {
    research: 'Scouting Facebook Marketplace for comparable prices',
    listing: 'Creating Facebook Marketplace listing — uploading photos',
  },
  mercari: {
    research: 'Checking Mercari pricing trends and demand signals',
    listing: 'Posting to Mercari — filling category, description, photos',
  },
  depop: {
    research: 'Browsing Depop for similar items in this category',
    listing: 'Creating Depop listing — setting price and shipping',
  },
};

const PLATFORM_COLORS = {
  ebay: '#FF6B6B',
  facebook: '#FF9F43',
  mercari: '#34D399',
  depop: '#FBBF24',
};

function generatePlaceholderBlob(platform, phase, status) {
  const canvas = document.createElement('canvas');
  canvas.width = 640;
  canvas.height = 400;
  const ctx = canvas.getContext('2d');

  const bg = { ebay: '#FFF1E6', facebook: '#FFF7F0', mercari: '#FFF3EA', depop: '#FFFAF4' };
  ctx.fillStyle = bg[platform] || '#FFF1E6';
  ctx.fillRect(0, 0, 640, 400);

  ctx.fillStyle = 'rgba(0,0,0,0.03)';
  ctx.fillRect(0, 0, 640, 48);

  const color = PLATFORM_COLORS[platform] || '#FF6B6B';

  ctx.fillStyle = color;
  ctx.globalAlpha = 0.12;
  ctx.beginPath();
  ctx.roundRect(24, 72, 592, 280, 8);
  ctx.fill();
  ctx.globalAlpha = 1;

  ctx.fillStyle = color;
  ctx.font = 'bold 22px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(platform.charAt(0).toUpperCase() + platform.slice(1), 24, 32);

  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.font = '13px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(phase.toUpperCase(), 616, 32);

  ctx.fillStyle = color;
  ctx.font = 'bold 18px system-ui, sans-serif';
  ctx.textAlign = 'center';

  const taskMap = {
    queued: 'Waiting in queue...',
    running: 'Opening browser...',
    navigating: `Navigating to ${platform}.com`,
    filling: phase === 'listing' ? 'Filling listing form fields' : 'Extracting price data',
    complete: 'Done',
    error: 'Error encountered',
  };
  ctx.fillText(taskMap[status] || status, 320, 200);

  if (status === 'navigating' || status === 'filling') {
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    for (let i = 0; i < 5; i++) {
      ctx.fillRect(40, 240 + i * 28, 200 + Math.random() * 200, 16);
    }
  }

  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
}

function generateFrameBlob(index, label) {
  const canvas = document.createElement('canvas');
  canvas.width = 480;
  canvas.height = 360;
  const ctx = canvas.getContext('2d');

  const palettes = [
    ['#FFECD2', '#FCB69F'], ['#A1C4FD', '#C2E9FB'],
    ['#D4FC79', '#96E6A1'], ['#FAD0C4', '#FFD1FF'],
    ['#FFECD2', '#FCB69F'], ['#E0C3FC', '#8EC5FC'],
  ];
  const [c1, c2] = palettes[index % palettes.length];
  const grad = ctx.createLinearGradient(0, 0, 480, 360);
  grad.addColorStop(0, c1);
  grad.addColorStop(1, c2);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 480, 360);

  ctx.globalAlpha = 0.06;
  for (let i = 0; i < 6; i++) {
    ctx.beginPath();
    ctx.arc(80 + i * 70, 180, 40 + i * 12, 0, Math.PI * 2);
    ctx.fillStyle = '#000';
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  ctx.save();
  ctx.globalAlpha = 0.08;
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.arc(240, 140, 90, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  const ts = `00:0${index}.${(index * 17) % 100}`;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.beginPath();
  ctx.roundRect(16, 310, 100, 32, 8);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = '600 13px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(ts, 28, 331);

  ctx.fillStyle = 'rgba(0,0,0,0.5)';
  ctx.beginPath();
  ctx.roundRect(340, 16, 124, 30, 8);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = '500 11px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(label || `Frame ${index + 1}`, 402, 35);

  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
}

const ITEM_VIEW_LABELS = ['Front', 'Side', 'Back', 'Detail'];

const ITEM_PALETTES = {
  'iPhone 15 Pro 256GB Natural Titanium': [
    ['#E8E0D4', '#C4B8A8'], ['#D5CEC2', '#B8AFA1'],
    ['#CCC3B5', '#AEA498'], ['#F0EBE3', '#D8D0C4'],
  ],
  'Apple AirPods Pro 2nd Gen USB-C': [
    ['#F5F5F5', '#E8E8E8'], ['#EFEFEF', '#DEDEDE'],
    ['#F0F0F0', '#E0E0E0'], ['#FAFAFA', '#ECECEC'],
  ],
  'Apple Watch Ultra 2 49mm Titanium': [
    ['#1C1C1E', '#3A3A3C'], ['#2C2C2E', '#48484A'],
    ['#1C1C1E', '#3A3A3C'], ['#FF9F0A', '#FF6B2C'],
  ],
};

function generateItemBlob(name, viewIndex = 0) {
  const canvas = document.createElement('canvas');
  canvas.width = 400;
  canvas.height = 400;
  const ctx = canvas.getContext('2d');
  const label = ITEM_VIEW_LABELS[viewIndex % ITEM_VIEW_LABELS.length];

  const palettes = ITEM_PALETTES[name] || [
    ['#FFECD2', '#FCB69F'], ['#E0C3FC', '#8EC5FC'],
    ['#D4FC79', '#96E6A1'], ['#FAD0C4', '#FFD1FF'],
  ];
  const [c1, c2] = palettes[viewIndex % palettes.length];

  const bg = ctx.createRadialGradient(200, 180, 20, 200, 200, 280);
  bg.addColorStop(0, c1);
  bg.addColorStop(1, c2);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, 400, 400);

  ctx.save();
  ctx.globalAlpha = 0.04;
  for (let r = 30; r < 200; r += 25) {
    ctx.beginPath();
    ctx.arc(200, 180, r, 0, Math.PI * 2);
    ctx.strokeStyle = '#000';
    ctx.lineWidth = 0.5;
    ctx.stroke();
  }
  ctx.restore();

  const isDark = c1.startsWith('#1') || c1.startsWith('#2') || c1.startsWith('#3');
  const textColor = isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.45)';
  const pillBg = isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.06)';

  ctx.save();
  ctx.globalAlpha = isDark ? 0.15 : 0.06;
  ctx.fillStyle = isDark ? '#fff' : '#000';
  ctx.beginPath();
  ctx.roundRect(110, 80, 180, 200, 24);
  ctx.fill();
  ctx.restore();

  const shortName = name.split(' ').slice(0, 3).join(' ');
  ctx.fillStyle = textColor;
  ctx.font = '600 16px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(shortName, 200, 190);

  const rest = name.split(' ').slice(3).join(' ');
  if (rest) {
    ctx.font = '400 12px system-ui, -apple-system, sans-serif';
    ctx.fillText(rest, 200, 212);
  }

  ctx.fillStyle = pillBg;
  const pillW = ctx.measureText(label.toUpperCase()).width + 24;
  ctx.beginPath();
  ctx.roundRect(200 - pillW / 2, 340, pillW, 28, 14);
  ctx.fill();
  ctx.fillStyle = textColor;
  ctx.font = '600 11px system-ui, -apple-system, sans-serif';
  ctx.letterSpacing = '1px';
  ctx.fillText(label.toUpperCase(), 200, 358);

  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
}

function buildAgentId(platform, phase, index) {
  return `${platform}-${phase}-${index}`;
}

function buildInitialAgents() {
  const agents = {};
  let idx = 0;
  for (const platform of PLATFORMS) {
    const rid = buildAgentId(platform, PHASE_RESEARCH, idx);
    agents[rid] = {
      agent_id: rid,
      platform,
      phase: PHASE_RESEARCH,
      status: STATUS_QUEUED,
      task: MOCK_TASKS[platform].research,
      started_at: null,
      completed_at: null,
      result: null,
      error: null,
    };
    idx++;
  }
  return agents;
}

const MOCK_ITEM_DEFS = [
  {
    item_id: 'item-1',
    name_guess: 'iPhone 15 Pro 256GB Natural Titanium',
    confidence: 0.96,
    visible_defects: [{ description: 'Minor scratch on back glass', severity: 'minor' }],
    spoken_defects: ['Small scratch mentioned by seller'],
  },
  {
    item_id: 'item-2',
    name_guess: 'Apple AirPods Pro 2nd Gen USB-C',
    confidence: 0.89,
    visible_defects: [],
    spoken_defects: [],
  },
  {
    item_id: 'item-3',
    name_guess: 'Apple Watch Ultra 2 49mm Titanium',
    confidence: 0.91,
    visible_defects: [{ description: 'Light scuff on titanium case edge', severity: 'minor' }],
    spoken_defects: ['Tiny mark on the side'],
  },
];

const MOCK_TRANSCRIPT = `"So I've got this iPhone 15 Pro here, the 256 gig Natural Titanium model. It's in pretty great shape overall — there's a small scratch on the back glass but honestly you can barely see it. Screen is perfect, no cracks. Battery health is at 94%. Then I've got these AirPods Pro, the second gen with USB-C — basically brand new, used them maybe twice. And lastly this Apple Watch Ultra 2, the 49mm titanium. There's a tiny scuff on the case edge but the screen is perfect. All three come with original boxes."`;

const V1_AGENTS = ['intake', 'condition_fusion', 'marketplace_resale', 'trade_in', 'return', 'repair_roi', 'route_decider', 'concierge'];

function buildMockBids() {
  return {
    'item-1': [
      {
        route_type: 'sell_as_is',
        viable: true,
        estimated_value: 849,
        confidence: 0.92,
        comparable_listings: [
          { platform: 'eBay', title: 'iPhone 15 Pro 256GB Natural Titanium Unlocked', price: 869, image_url: null },
          { platform: 'eBay', title: 'Apple iPhone 15 Pro 256GB - Excellent Condition', price: 839, image_url: null },
          { platform: 'Mercari', title: 'iPhone 15 Pro 256GB Titanium Mint', price: 845, image_url: null },
          { platform: 'Facebook', title: 'iPhone 15 Pro 256gb Natural Titanium', price: 825, image_url: null },
        ],
      },
      {
        route_type: 'trade_in',
        viable: true,
        estimated_value: 630,
        confidence: 0.95,
        trade_in_quotes: [
          { provider: 'Apple Trade In', payout: 630, speed: '5-7 days', effort: 'Low', confidence: 0.95 },
          { provider: 'Best Buy', payout: 600, speed: '3-5 days', effort: 'Low', confidence: 0.90 },
          { provider: 'Decluttr', payout: 580, speed: '7-10 days', effort: 'Low', confidence: 0.88 },
        ],
      },
      { route_type: 'repair_then_sell', viable: true, estimated_value: 890, confidence: 0.78 },
      { route_type: 'return', viable: false, estimated_value: 0, confidence: 0.3 },
    ],
    'item-2': [
      {
        route_type: 'sell_as_is',
        viable: true,
        estimated_value: 185,
        confidence: 0.91,
        comparable_listings: [
          { platform: 'eBay', title: 'AirPods Pro 2nd Gen USB-C BNIB', price: 195, image_url: null },
          { platform: 'Mercari', title: 'Apple AirPods Pro 2 USB-C New', price: 180, image_url: null },
        ],
      },
      {
        route_type: 'trade_in',
        viable: true,
        estimated_value: 90,
        confidence: 0.85,
        trade_in_quotes: [
          { provider: 'Apple Trade In', payout: 90, speed: '5-7 days', effort: 'Low', confidence: 0.9 },
        ],
      },
      { route_type: 'repair_then_sell', viable: false, estimated_value: 0, confidence: 0.1 },
      { route_type: 'return', viable: false, estimated_value: 0, confidence: 0.2 },
    ],
  };
}

function buildMockDecisions() {
  return {
    'item-1': {
      best_route: 'sell_as_is',
      estimated_best_value: 849,
      route_reason: 'Resale yields highest net value. Minor scratch has negligible impact on pricing.',
      winning_bid: { route_type: 'sell_as_is', viable: true, estimated_value: 849 },
      alternatives: [
        { route_type: 'repair_then_sell', viable: true, estimated_value: 890 },
        { route_type: 'trade_in', viable: true, estimated_value: 630 },
      ],
    },
    'item-2': {
      best_route: 'sell_as_is',
      estimated_best_value: 185,
      route_reason: 'Basically new condition. Direct resale is optimal, trade-in significantly undervalues.',
      winning_bid: { route_type: 'sell_as_is', viable: true, estimated_value: 185 },
      alternatives: [
        { route_type: 'trade_in', viable: true, estimated_value: 90 },
      ],
    },
  };
}

export function useMockMode() {
  const isMock = useMemo(() => {
    if (typeof window === 'undefined') return false;
    return new URLSearchParams(window.location.search).has('mock');
  }, []);

  const [mockJobId] = useState(() => isMock ? 'mock-job-' + Date.now() : null);
  const [v2Agents, setV2Agents] = useState({});
  const [pipelineStage, setPipelineStage] = useState('intake');
  const [screenshots, setScreenshots] = useState(new Map());
  const [items, setItems] = useState([]);
  const [job, setJob] = useState(null);
  const [started, setStarted] = useState(false);
  const [agents, setAgents] = useState({});
  const [agentsRaw, setAgentsRaw] = useState({});
  const [agentsByItem, setAgentsByItem] = useState({});
  const [stage3Plan, setStage3Plan] = useState(null);
  const [bids, setBids] = useState({});
  const [decisions, setDecisions] = useState({});
  const [events, setEvents] = useState([]);
  const blobUrlsRef = useRef(new Map());
  const timersRef = useRef([]);
  const frameUrlsRef = useRef([]);
  const itemUrlsRef = useRef([]);

  const cleanup = useCallback(() => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
    blobUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    blobUrlsRef.current.clear();
    frameUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    frameUrlsRef.current = [];
    itemUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    itemUrlsRef.current = [];
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const generateScreenshot = useCallback(async (agentId, platform, phase, status = 'running') => {
    const blob = await generatePlaceholderBlob(platform, phase, status);
    const prevUrl = blobUrlsRef.current.get(agentId);
    if (prevUrl) URL.revokeObjectURL(prevUrl);
    const url = URL.createObjectURL(blob);
    blobUrlsRef.current.set(agentId, url);
    setScreenshots((prev) => {
      const next = new Map(prev);
      next.set(agentId, { url, timestamp: Math.floor(Date.now() / 1000) });
      return next;
    });
  }, []);

  const pushEvent = useCallback((type, data) => {
    setEvents((prev) => [...prev.slice(-100), { type, data, timestamp: Date.now() }]);
  }, []);

  const setV1Agent = useCallback((agentId, status, message, extra = {}) => {
    setAgents((prev) => ({
      ...prev,
      [agentId]: { status, message, elapsed_ms: extra.elapsed_ms || null, ...extra },
    }));
    pushEvent('agent_status', { agent: agentId, status, message });
  }, [pushEvent]);

  const advanceAgent = useCallback((agentId, currentIdx) => {
    const nextIdx = currentIdx + 1;
    if (nextIdx >= STATUS_SEQUENCE.length) return;

    const nextStatus = STATUS_SEQUENCE[nextIdx];
    setV2Agents((prev) => {
      const agent = prev[agentId];
      if (!agent) return prev;
      const updated = { ...agent, status: nextStatus };
      if (nextIdx === 1) updated.started_at = Date.now() / 1000;
      if (nextStatus === STATUS_COMPLETE) updated.completed_at = Date.now() / 1000;
      return { ...prev, [agentId]: updated };
    });
  }, []);

  const startMockPipeline = useCallback(async () => {
    if (!isMock || started) return mockJobId;
    setStarted(true);
    cleanup();

    setJob({ job_id: mockJobId, status: 'processing' });
    setPipelineStage('intake');

    // Generate frame images
    const frameLabels = ['Wide shot', 'iPhone close-up', 'Back glass', 'Screen detail', 'AirPods box', 'AirPods close-up'];
    const frameBlobs = await Promise.all(frameLabels.map((label, i) => generateFrameBlob(i, label)));
    const frameUrls = frameBlobs.map((blob) => {
      const url = URL.createObjectURL(blob);
      frameUrlsRef.current.push(url);
      return url;
    });

    const VIEWS_PER_ITEM = 4;
    const itemFrameUrls = [];
    for (const def of MOCK_ITEM_DEFS) {
      const blobs = await Promise.all(
        Array.from({ length: VIEWS_PER_ITEM }, (_, v) => generateItemBlob(def.name_guess, v))
      );
      const urls = blobs.map((blob) => {
        const url = URL.createObjectURL(blob);
        itemUrlsRef.current.push(url);
        return url;
      });
      itemFrameUrls.push(urls);
    }

    const S = 10000;
    const D = 6000;

    // ── STAGE 1: Processing / Intake ──
    const t0 = setTimeout(() => {
      setV1Agent('intake', 'agent_started', 'Extracting frames from video...');
      setPipelineStage('analysis');
    }, 500);
    timersRef.current.push(t0);

    const t1 = setTimeout(() => {
      setV1Agent('intake', 'agent_progress', 'Extracted 6 frames, transcribing audio...', {
        frame_paths: frameUrls,
        elapsed_ms: 2000 + D,
      });
      setJob((prev) => ({ ...prev, frame_paths: frameUrls }));
    }, 2000 + D);
    timersRef.current.push(t1);

    const t2 = setTimeout(() => {
      setV1Agent('intake', 'agent_progress', 'Transcription complete. Running item detection...', {
        frame_paths: frameUrls,
        transcript_text: MOCK_TRANSCRIPT,
        elapsed_ms: 4500 + D,
      });
      setJob((prev) => ({ ...prev, frame_paths: frameUrls, transcript_text: MOCK_TRANSCRIPT }));
    }, 4500 + D);
    timersRef.current.push(t2);

    const t3 = setTimeout(() => {
      const richItems = MOCK_ITEM_DEFS.map((def, i) => ({
        ...def,
        hero_frame_paths: itemFrameUrls[i],
      }));
      setItems(richItems);
      setV1Agent('intake', 'agent_completed', `Found ${richItems.length} items`, {
        frame_paths: frameUrls,
        transcript_text: MOCK_TRANSCRIPT,
        elapsed_ms: 6500 + D,
      });
    }, 6500 + D);
    timersRef.current.push(t3);

    const t4 = setTimeout(() => {
      setV1Agent('condition_fusion', 'agent_started', 'Analyzing condition for all items...');
    }, 6500 + D + 500);
    timersRef.current.push(t4);

    const t5 = setTimeout(() => {
      setV1Agent('condition_fusion', 'agent_progress', 'Inspecting iPhone 15 Pro — checking screen, back glass, ports...', {
        elapsed_ms: 2000,
      });
    }, 8500 + D);
    timersRef.current.push(t5);

    const t6 = setTimeout(() => {
      setV1Agent('condition_fusion', 'agent_progress', 'Inspecting AirPods Pro — verifying case, buds, charging port...', {
        elapsed_ms: 4500,
      });
    }, 11000 + D);
    timersRef.current.push(t6);

    const t7 = setTimeout(() => {
      setV1Agent('condition_fusion', 'agent_completed', 'Condition analysis complete for 2 items', {
        elapsed_ms: 7000,
      });
    }, 13500 + D);
    timersRef.current.push(t7);

    // ── STAGE 2: Research Phase ──────────────────────
    const t8 = setTimeout(() => {
      setPipelineStage('research');
      setBids(buildMockBids());
    }, 14500 + D);
    timersRef.current.push(t8);

    const t9 = setTimeout(() => {
      setDecisions(buildMockDecisions());
    }, 16000 + D);
    timersRef.current.push(t9);

    return mockJobId;
  }, [isMock, started, mockJobId, cleanup, generateScreenshot, advanceAgent, setV1Agent, pushEvent]);

  const send = useCallback(() => {}, []);

  return {
    isMock,
    mockJobId,
    v2Agents,
    pipelineStage,
    screenshots,
    items,
    job,
    agents,
    agentsRaw,
    agentsByItem,
    stage3Plan,
    bids,
    decisions,
    events,
    startMockPipeline,
    send,
  };
}
