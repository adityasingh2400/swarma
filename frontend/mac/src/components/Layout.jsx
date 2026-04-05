import { useState, useMemo, useEffect, lazy, Suspense } from 'react';
import { motion, AnimatePresence, LayoutGroup } from 'framer-motion';
import { Scan, Check, ArrowRight } from 'lucide-react';
import IntakePanel from './panels/IntakePanel';
import AgentTheater from './panels/AgentTheater';
import DecisionPanel from './panels/DecisionPanel';
import FocusMode from './FocusMode';
import ResearchPage from './research/ResearchPage';
import ConciergePage from './ConciergePage';
import { ACTIVE_STATUSES } from '../utils/contracts';

/* Lazy-load preview-only modules so they don't bloat the main bundle */
const MarketSweep = lazy(() => import('./modules/MarketSweep'));
const BestRoute = lazy(() => import('./modules/BestRoute'));
const QuoteSweep = lazy(() => import('./modules/QuoteSweep'));
const RepairSweep = lazy(() => import('./modules/RepairSweep'));
const BundleMerge = lazy(() => import('./modules/BundleMerge'));
const AssetStudio = lazy(() => import('./modules/AssetStudio'));
const PostingWorkspace = lazy(() => import('./modules/PostingWorkspace'));
const UnifiedInbox = lazy(() => import('./modules/UnifiedInbox'));
const ConditionFusion = lazy(() => import('./modules/ConditionFusion'));
const MultiPostEngine = lazy(() => import('./modules/MultiPostEngine'));

const EASE = [0.32, 0.72, 0, 1];

/* ══════════════════════════════════════════════════════════
   Dev preview mode
   ──────────────────────────────────────────────────────────
   Add ?preview=<page> to the URL to jump straight to any
   page with mock data.  See /flags.txt for the full list.
   ══════════════════════════════════════════════════════════ */
const DEV_PREVIEW = new URLSearchParams(window.location.search).get('preview');

const PREVIEW_PAGES = [
  'intake', 'research', 'decisions', 'concierge', 'market-sweep', 'best-route',
  'quote-sweep', 'repair-sweep', 'bundle-merge', 'asset-studio',
  'posting-workspace', 'unified-inbox', 'condition-fusion', 'multi-post',
];

/* ── Mock data factories ── */

function makeMockItems(count = 4) {
  const catalog = [
    { name: 'iPhone 14 Pro Max 256GB', defects: [] },
    { name: 'MacBook Air M2 2022', defects: [{ description: 'Minor scratch on screen' }] },
    { name: 'Sony WH-1000XM5 Headphones', defects: [] },
    { name: 'iPad Pro 11" M2', defects: [{ description: 'Small dent on corner' }] },
    { name: 'AirPods Pro 2nd Gen', defects: [] },
    { name: 'Samsung Galaxy S24 Ultra', defects: [] },
  ];
  return Array.from({ length: count }, (_, i) => {
    const c = catalog[i % catalog.length];
    return {
      item_id: `mock-item-${i}`,
      name_guess: c.name,
      hero_frame_paths: [`https://picsum.photos/seed/swarma${i}/400/400`],
      visible_defects: c.defects,
      spoken_defects: [],
      condition: c.defects.length ? 'Good' : 'Excellent',
      extracted_frames: Array.from({ length: 6 }, (_, j) => `https://picsum.photos/seed/frame${i}-${j}/320/240`),
    };
  });
}

function makeMockBids(items) {
  const bids = {};
  items.forEach((item) => {
    const base = 150 + Math.random() * 350;
    bids[item.item_id] = [
      {
        route_type: 'sell_as_is', estimated_value: Math.round(base), confidence: 0.7 + Math.random() * 0.25, viable: true,
        comparable_listings: [
          { platform: 'eBay', price: Math.round(base + 20 + Math.random() * 60), title: `${item.name_guess} - Great condition`, condition: 'Used - Like New', image_url: `https://picsum.photos/seed/eb${item.item_id}/200/200`, url: '#', match_score: 85 + Math.random() * 15 },
          { platform: 'Mercari', price: Math.round(base - 10 + Math.random() * 40), title: `${item.name_guess} - Like new`, condition: 'Good', image_url: `https://picsum.photos/seed/mc${item.item_id}/200/200`, url: '#', match_score: 78 + Math.random() * 15 },
          { platform: 'Facebook', price: Math.round(base - 30 + Math.random() * 50), title: `${item.name_guess} - Barely used`, condition: 'Used', image_url: `https://picsum.photos/seed/fb${item.item_id}/200/200`, url: '#', match_score: 70 + Math.random() * 15 },
        ],
      },
      { route_type: 'trade_in', estimated_value: Math.round(base * 0.65), confidence: 0.88, viable: true, provider: 'Apple Trade In', speed: 'days', effort: 'Low', payout: Math.round(base * 0.65) },
      { route_type: 'repair_then_sell', estimated_value: Math.round(base * 1.3), confidence: 0.6, viable: item.visible_defects?.length > 0, repair_parts: [
        { part_name: 'Screen Assembly', part_price: 45, source: 'Amazon', part_image_url: `https://picsum.photos/seed/part0/200/200` },
        { part_name: 'Battery Kit', part_price: 25, source: 'eBay', part_image_url: `https://picsum.photos/seed/part1/200/200` },
      ]},
    ];
  });
  return bids;
}

function makeMockDecisions(items, bids) {
  const decisions = {};
  const routes = ['sell_as_is', 'trade_in', 'repair_then_sell', 'sell_as_is'];
  items.forEach((item, i) => {
    const best = routes[i % routes.length];
    const itemBids = bids[item.item_id] || [];
    const winBid = itemBids.find(b => b.route_type === best) || itemBids[0];
    decisions[item.item_id] = {
      best_route: best,
      estimated_best_value: winBid?.estimated_value || 250,
      route_reason: `Best return on ${item.name_guess} via ${best.replace(/_/g, ' ')} based on market analysis.`,
      winning_bid: winBid,
      alternatives: itemBids.filter(b => b.route_type !== best),
    };
  });
  return decisions;
}

function makeMockListings(items) {
  const platforms = ['ebay', 'mercari', 'facebook'];
  return items.reduce((acc, item, i) => {
    acc[item.item_id] = platforms.slice(0, 2 + (i % 2)).map((p) => ({
      platform: p,
      title: `${item.name_guess} - ${p === 'ebay' ? 'Free Shipping!' : 'Great Deal'}`,
      price: 180 + Math.round(Math.random() * 200),
      status: i === 0 ? 'live' : 'draft',
      url: '#',
      image_url: item.hero_frame_paths?.[0],
    }));
    return acc;
  }, {});
}

function makeMockThreads(items) {
  return items.slice(0, 2).map((item, i) => ({
    thread_id: `thread-${i}`,
    platform: i === 0 ? 'ebay' : 'mercari',
    buyer: { handle: i === 0 ? 'techbuyer92' : 'dealfinder_x', rating: 4.8 },
    item_id: item.item_id,
    item_name: item.name_guess,
    messages: [
      { from: 'buyer', text: `Hi, is the ${item.name_guess} still available?`, ts: Date.now() - 3600000 },
      { from: 'seller', text: 'Yes! It\'s in great condition. Would you like more photos?', ts: Date.now() - 1800000 },
      { from: 'buyer', text: 'What\'s the lowest you\'d go?', ts: Date.now() - 600000 },
    ],
    offer: i === 0 ? 195 : null,
    seriousness: i === 0 ? 'high' : 'medium',
    suggested_reply: 'I can do $5 off if you buy today!',
  }));
}

function makeMockJob() {
  return {
    job_id: 'mock-job-001',
    status: 'processing',
    video_filename: 'demo-items.mp4',
    created_at: new Date().toISOString(),
    transcript: 'So I have this iPhone 14 Pro Max, it\'s in great shape. Then there\'s this MacBook Air M2, has a small scratch on the screen but works perfectly...',
  };
}

/* ── Preview navigation bar ── */

function PreviewNav() {
  const navStyle = {
    padding: '10px 16px', fontSize: 10, fontWeight: 600, letterSpacing: '0.1em',
    textTransform: 'uppercase', color: 'var(--text-tertiary)',
    display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
    borderBottom: '1px solid var(--border)', flexShrink: 0, background: 'var(--bg-card)',
  };
  const linkStyle = (active) => ({
    color: active ? 'var(--primary)' : 'var(--text-secondary)',
    textDecoration: 'none', padding: '3px 8px', borderRadius: 6,
    background: active ? 'var(--primary-dim)' : 'transparent',
    transition: 'all 0.15s ease',
  });
  return (
    <div style={navStyle}>
      <span style={{ marginRight: 4 }}>Preview:</span>
      {PREVIEW_PAGES.map((p) => (
        <a key={p} href={`?preview=${p}`} style={linkStyle(DEV_PREVIEW === p)}>{p}</a>
      ))}
      <a href="/" style={{ ...linkStyle(false), marginLeft: 'auto', color: 'var(--text-tertiary)' }}>✕ Exit</a>
    </div>
  );
}

/* ── Preview renderer ── */

function DevPreview() {
  const mock = useMemo(() => {
    const items = makeMockItems(4);
    const bids = makeMockBids(items);
    const decisions = makeMockDecisions(items, bids);
    const listings = makeMockListings(items);
    const threads = makeMockThreads(items);
    const job = makeMockJob();
    return { items, bids, decisions, listings, threads, job };
  }, []);

  const page = DEV_PREVIEW;
  const noop = () => {};

  return (
    <div className="layout layout-unified" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <PreviewNav />
      <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
        <Suspense fallback={<div style={{ padding: 40, textAlign: 'center', color: 'var(--text-tertiary)' }}>Loading preview...</div>}>
          {page === 'intake' && (
            <IntakePanel onUpload={noop} fullscreen />
          )}
          {page === 'research' && (
            <ResearchPage items={mock.items} bids={mock.bids} decisions={mock.decisions} />
          )}
          {page === 'decisions' && (
            <DecisionPanel items={mock.items} decisions={mock.decisions} agents={{}} onExecuteItem={noop} fullscreen />
          )}
          {page === 'concierge' && (
            <ConciergePage items={mock.items} decisions={mock.decisions} listings={mock.listings} threads={mock.threads} postingStatus={{}} screenshots={new Map()} jobId="mock-preview" onUpload={noop} onSendReply={noop} send={noop} />
          )}
          {page === 'market-sweep' && (
            <MarketSweep job={mock.job} items={mock.items} bids={mock.bids} decisions={mock.decisions} />
          )}
          {page === 'best-route' && (
            <BestRoute decisions={mock.decisions} />
          )}
          {page === 'quote-sweep' && (
            <QuoteSweep bids={Object.values(mock.bids)[0]} />
          )}
          {page === 'repair-sweep' && (
            <RepairSweep items={mock.items} bids={mock.bids} />
          )}
          {page === 'bundle-merge' && (
            <BundleMerge items={mock.items} bids={mock.bids} decisions={mock.decisions} />
          )}
          {page === 'asset-studio' && (
            <AssetStudio items={mock.items} listings={mock.listings} />
          )}
          {page === 'posting-workspace' && (
            <PostingWorkspace items={mock.items} decisions={mock.decisions} postingStatus={{}} />
          )}
          {page === 'unified-inbox' && (
            <UnifiedInbox threads={mock.threads} onSendReply={noop} />
          )}
          {page === 'condition-fusion' && (
            <ConditionFusion items={mock.items} job={mock.job} />
          )}
          {page === 'multi-post' && (
            <MultiPostEngine items={mock.items} listings={mock.listings} onExecuteItem={noop} />
          )}
        </Suspense>
      </div>
    </div>
  );
}

function getGlobalStage(agents, v2Agents, pipelineStage) {
  if (pipelineStage) return pipelineStage;

  const v2Entries = Object.values(v2Agents || {});
  if (v2Entries.length > 0) {
    const hasActive = v2Entries.some((a) => ACTIVE_STATUSES.has(a.status));
    const allComplete = v2Entries.every((a) => a.status === 'complete' || a.status === 'error');
    if (allComplete) return 'concierge-done';
    if (hasActive) return 'research';
  }

  const s = (id) => {
    const v = agents[id]?.status;
    if (v === 'agent_started' || v === 'thinking' || v === 'agent_progress') return 'thinking';
    if (v === 'agent_completed' || v === 'done') return 'done';
    return 'idle';
  };
  if (s('concierge') === 'done') return 'concierge-done';
  if (s('concierge') === 'thinking') return 'concierge';
  if (s('route_decider') === 'done' || s('route_decider') === 'thinking') return 'deciding';
  const routeAgents = ['marketplace_resale', 'trade_in', 'return', 'repair_roi'];
  if (routeAgents.some((a) => s(a) === 'thinking' || s(a) === 'done')) return 'research';
  if (s('condition_fusion') === 'done' || s('condition_fusion') === 'thinking') return 'processing';
  if (s('intake') === 'done' || s('intake') === 'thinking') return 'processing';
  return 'idle';
}

function MiniPlayer({ videoUrl, items, globalStage, agents }) {
  const hasItems = items.length > 0;
  const intakeStatus = agents?.intake?.status;
  const isAnalyzing = !hasItems && globalStage !== 'idle' && globalStage !== 'concierge-done';
  const frameCount = agents?.intake?.frame_paths?.length || 0;

  let statusText = '';
  if (hasItems) {
    statusText = `${items.length} item${items.length !== 1 ? 's' : ''} detected`;
  } else if (frameCount > 0) {
    statusText = `${frameCount} frames extracted`;
  } else if (intakeStatus === 'agent_started' || intakeStatus === 'agent_progress') {
    statusText = 'Analyzing...';
  }

  return (
    <div className="mp-wrap">
      <motion.div
        className="mp-frame"
        layoutId="video-player"
        transition={{ type: 'spring', damping: 30, stiffness: 180, mass: 1 }}
      >
        <video src={videoUrl} muted autoPlay loop playsInline />
        {isAnalyzing && <div className="mp-scanbar" />}
      </motion.div>
      <AnimatePresence mode="wait">
        {statusText && (
          <motion.div
            key={statusText}
            className={`mp-status-pill ${hasItems ? 'mp-status-done' : ''}`}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.3 }}
          >
            {hasItems ? <Check size={10} /> : <Scan size={10} />}
            <span>{statusText}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function Layout(props) {
  if (DEV_PREVIEW) return <DevPreview />;
  return <LayoutInner {...props} />;
}

function LayoutInner({
  job, items, bids, decisions, listings, threads, agents,
  agentsRaw, agentsByItem, stage3Plan, events, lastEvent,
  onUpload, onExecuteItem, onSendReply,
  v2Agents = {}, pipelineStage, postingStatus = {}, send, screenshots,
  theaterNavRequest,
  onTheaterNavConsumed,
  onTheaterStageChange,
}) {
  const [phase, setPhase] = useState('intake');
  const [videoUrl, setVideoUrl] = useState(null);
  const [focusedAgentId, setFocusedAgentId] = useState(null);
  const [researchReady, setResearchReady] = useState(false);

  useEffect(() => {
    return () => { if (videoUrl) URL.revokeObjectURL(videoUrl); };
  }, [videoUrl]);

  const globalStage = useMemo(
    () => getGlobalStage(agents, v2Agents, pipelineStage),
    [agents, v2Agents, pipelineStage],
  );

  const showConciergeResults = globalStage === 'concierge-done' || globalStage === 'concierge';
  const researchGateOpen = false;

  const handleUpload = (file, url) => {
    setVideoUrl(url);
    setPhase('processing');
    onUpload(file);
  };

  const focusedAgent = focusedAgentId ? v2Agents[focusedAgentId] : null;
  const focusedShot = focusedAgentId && screenshots
    ? (screenshots instanceof Map ? screenshots.get(focusedAgentId) : screenshots[focusedAgentId])
    : null;

  return (
    <LayoutGroup>
      <motion.div
        className="layout layout-unified"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, ease: EASE }}
      >
        <AnimatePresence mode="wait">
          {/* ── Phase: Intake ───────────────────────────────── */}
          {phase === 'intake' && (
            <motion.div
              key="intake-full"
              className="intake-fullscreen"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{
                opacity: 0,
                scale: 0.97,
                filter: 'blur(4px)',
                transition: { duration: 0.5, ease: [0.4, 0, 0.2, 1] },
              }}
              transition={{ duration: 0.3, ease: EASE }}
            >
              <IntakePanel onUpload={handleUpload} fullscreen />
            </motion.div>
          )}

          {/* ── Phase: Processing ───────────────────────────── */}
          {phase === 'processing' && !showConciergeResults && !researchGateOpen && (
            <motion.div
              key="processing"
              className="proc-layout"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, filter: 'blur(4px)', transition: { duration: 0.3 } }}
              transition={{ duration: 0.4, ease: EASE }}
            >
              {viewOverride && (globalStage === 'concierge-done' || globalStage === 'concierge') && (
                <motion.button
                  className="view-override-banner"
                  onClick={() => setViewOverride(null)}
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, ease: EASE }}
                >
                  <span>Results are ready</span>
                  <ArrowRight size={14} />
                  <span>View Decisions</span>
                </motion.button>
              )}

              <motion.div
                className="proc-pipeline"
                initial={{ opacity: 0, y: -16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, delay: 0.05, ease: EASE }}
              >
                <AgentTheater
                  job={job} items={items} bids={bids} decisions={decisions}
                  listings={listings} threads={threads} agents={agents}
                  agentsRaw={agentsRaw} agentsByItem={agentsByItem}
                  stage3Plan={stage3Plan} events={events} lastEvent={lastEvent}
                  onExecuteItem={onExecuteItem} onSendReply={onSendReply}
                  v2Agents={v2Agents} pipelineStage={pipelineStage} postingStatus={postingStatus} send={send}
                  theaterNavRequest={theaterNavRequest}
                  onTheaterNavConsumed={onTheaterNavConsumed}
                  onStageClick={onTheaterStageChange}
                  miniPlayer={videoUrl ? (
                    <MiniPlayer videoUrl={videoUrl} items={items} globalStage={globalStage} agents={agents} />
                  ) : null}
                />
              </motion.div>
            </motion.div>
          )}

          {/* ── Phase: Research ─────────────────────────────── */}
          {phase === 'processing' && researchGateOpen && !showConciergeResults && (
            <motion.div
              key="research"
              className="research-fullscreen"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, transition: { duration: 0.3 } }}
              transition={{ duration: 0.5, ease: EASE }}
            >
              <ResearchPage
                items={items}
                bids={bids}
                decisions={decisions}
                v2Agents={v2Agents}
                screenshots={screenshots}
                send={send}
              />
            </motion.div>
          )}

          {/* ── Phase: Concierge Results ────────────────────── */}
          {phase === 'processing' && showConciergeResults && (
            <motion.div
              key="concierge-results"
              className="concierge-fullscreen"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.2 } }}
              transition={{ duration: 0.4, ease: EASE }}
            >
              <ConciergePage
                items={items}
                decisions={decisions}
                listings={listings}
                threads={threads}
                postingStatus={postingStatus}
                screenshots={screenshots}
                jobId={job?.job_id}
                onUpload={handleUpload}
                onSendReply={onSendReply}
                send={send}
              />
            </motion.div>
          )}
        </AnimatePresence>

        <FocusMode
          agent={focusedAgent}
          screenshotUrl={focusedShot?.url}
          onClose={() => setFocusedAgentId(null)}
          send={send}
        />
      </motion.div>
    </LayoutGroup>
  );
}
