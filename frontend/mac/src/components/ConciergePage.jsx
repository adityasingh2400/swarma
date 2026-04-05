import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Eye, Package, X, ChevronLeft, ChevronRight,
  MessageSquare, Send, Star, Check, ExternalLink,
  Tag, Truck, Globe, Monitor, Loader2,
} from 'lucide-react';
import SwarmaLogo from './SwarmaLogo';
import BrowserFeed from './BrowserFeed';
import ItemDetailModal from './shared/ItemDetailModal';

const EASE = [0.32, 0.72, 0, 1];

const PLATFORM_META = {
  facebook: { label: 'Facebook', color: '#1877f2', accent: '#1877f2' },
  depop: { label: 'Depop', color: '#ff2300', accent: '#ff2300' },
};

function formatPrice(price) {
  return price?.toFixed?.(2) || '0.00';
}

// ── Live Chat (polls real backend) ───────────────────────────────────────────

function LiveConversation({ itemId, jobId, platform }) {
  const [threads, setThreads] = useState([]);
  const [replyText, setReplyText] = useState({});
  const scrollContainerRef = useRef(null);

  const fetchThreads = useCallback(async () => {
    if (!jobId) return;
    try {
      const BASE = window.location.origin || '';
      const r = await fetch(`${BASE}/api/jobs/${jobId}/inbox`);
      if (!r.ok) return;
      const all = await r.json();
      // Show all threads — FB inbox polling can't reliably map
      // conversations to specific items, so surface everything.
      const filtered = all;

      const enriched = await Promise.all(filtered.map(async (t) => {
        const lastMsg = t.messages?.[t.messages.length - 1];
        if (lastMsg?.sender === 'buyer' && !t.suggested_reply) {
          try {
            const sr = await fetch(`${BASE}/api/jobs/${jobId}/inbox/${t.thread_id}/suggest`);
            if (sr.ok) {
              const { suggested_reply } = await sr.json();
              return { ...t, suggested_reply };
            }
          } catch { /* ignore */ }
        }
        return t;
      }));
      setThreads(enriched);
    } catch (err) {
      console.error('Failed to fetch inbox:', err);
    }
  }, [jobId, itemId]);

  useEffect(() => {
    fetchThreads();
    const interval = setInterval(fetchThreads, 3000);
    return () => clearInterval(interval);
  }, [fetchThreads]);

  useEffect(() => {
    scrollContainerRef.current?.scrollTo({ top: scrollContainerRef.current.scrollHeight, behavior: 'smooth' });
  }, [threads]);

  const handleSend = useCallback(async (threadId) => {
    const text = replyText[threadId]?.trim();
    if (!text || !jobId) return;
    setReplyText(prev => ({ ...prev, [threadId]: '' }));
    try {
      const BASE = window.location.origin || '';
      await fetch(`${BASE}/api/jobs/${jobId}/inbox/${threadId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      fetchThreads();
    } catch (err) {
      console.error('Failed to send reply:', err);
    }
  }, [replyText, jobId, fetchThreads]);

  const meta = PLATFORM_META[platform] || PLATFORM_META.facebook;

  if (threads.length === 0) {
    return (
      <div className="conc-chat-empty">
        <MessageSquare size={28} style={{ opacity: 0.3 }} />
        <p>No buyer conversations yet</p>
        <p className="conc-chat-empty-hint">Messages will appear here when buyers reach out</p>
      </div>
    );
  }

  return (
    <div className="conc-conversations" ref={scrollContainerRef} style={{ '--platform-color': meta.color }}>
      {threads.map(thread => {
        return (
          <div key={thread.thread_id} className="conc-thread glass-card">
            <div className="conc-thread-header">
              <span className="conc-thread-buyer">{thread.buyer_handle || 'Buyer'}</span>
              {thread.is_winning && <Star size={12} fill="var(--success)" color="var(--success)" />}
              {thread.current_offer != null && (
                <span className="conc-thread-offer">${thread.current_offer}</span>
              )}
            </div>
            <div className="conc-thread-messages">
              {(thread.messages || []).map((msg, i) => (
                <div key={i} className={`conc-msg conc-msg-${msg.sender}`}>
                  <span>{msg.text}</span>
                </div>
              ))}
            </div>
            {thread.suggested_reply && (
              <div
                className="conc-thread-suggestion"
                onClick={() => setReplyText(prev => ({ ...prev, [thread.thread_id]: thread.suggested_reply }))}
              >
                <span className="conc-suggestion-label">AI Suggested Reply</span>
                <span>{thread.suggested_reply}</span>
              </div>
            )}
            <div className="conc-thread-reply">
              <input
                placeholder="Type a reply..."
                value={replyText[thread.thread_id] || ''}
                onChange={e => setReplyText(prev => ({ ...prev, [thread.thread_id]: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && handleSend(thread.thread_id)}
              />
              <button onClick={() => handleSend(thread.thread_id)}><Send size={14} /></button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Concierge Slide (one per item in carousel) ─────────────────────────────

function ConciergeSlide({ item, decision, screenshots, listings, jobId }) {
  const itemId = item?.item_id;
  const title = item?.name_guess || 'Item';
  const heroImg = item?.hero_frame_paths?.[0];
  const price = decision?.estimated_best_value || listings?.[itemId]?.price_strategy || 0;

  // Concierge agent screencast key
  const agentId = `fb-concierge-${(itemId || '').slice(0, 8)}`;
  const shot = screenshots instanceof Map ? screenshots.get(agentId) : screenshots?.[agentId];
  const screenshotUrl = shot?.url || null;

  return (
    <div className="cc-slide">
      <div className="cc-slide-left">
        {/* Item card */}
        <div className="cc-item-card glass-card">
          <div className="cc-item-img">
            {heroImg
              ? <img src={heroImg} alt={title} />
              : <Package size={32} strokeWidth={1.2} style={{ opacity: 0.3 }} />
            }
          </div>
          <div className="cc-item-info">
            <h3 className="cc-item-name">{title}</h3>
            {price > 0 && <span className="cc-item-price">${formatPrice(price)}</span>}
            <div className="cc-item-status">
              <span className="cc-live-dot" />
              <span>Live on Facebook</span>
            </div>
          </div>
        </div>

        {/* Browser feed */}
        <div className="cc-browser glass-card">
          <div className="pw-browser-mock">
            <div className="pw-browser-chrome">
              <div className="pw-browser-dots"><span /><span /><span /></div>
              <div className="pw-browser-url">
                <Globe size={9} className="pw-browser-url-icon" />
                <span>facebook.com/marketplace</span>
              </div>
              <motion.span
                className="pw-browser-live-badge"
                animate={{ opacity: [1, 0.4, 1] }}
                transition={{ duration: 1.5, repeat: Infinity }}
                style={{ fontSize: 9, fontWeight: 700, color: '#4ade80', marginLeft: 'auto', marginRight: 6 }}
              >LIVE</motion.span>
            </div>
            <div className="pw-browser-body">
              {screenshotUrl ? (
                <BrowserFeed screenshotUrl={screenshotUrl} size="thumbnail" />
              ) : (
                <div className="pw-browser-fallback pw-browser-fallback-visible">
                  <Monitor size={20} strokeWidth={1.25} />
                  <span>Agent monitoring inbox...</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Right: Live chat */}
      <div className="cc-slide-right glass-card">
        <div className="cc-chat-header">
          <MessageSquare size={14} />
          <span>Buyer Messages</span>
        </div>
        <LiveConversation itemId={itemId} jobId={jobId} platform="facebook" />
      </div>
    </div>
  );
}

// ── Concierge Carousel (PostingWorkspace-style) ─────────────────────────────

const slideVariants = {
  enter: (dir) => ({ x: dir > 0 ? 300 : -300, opacity: 0, scale: 0.95 }),
  center: { x: 0, opacity: 1, scale: 1 },
  exit: (dir) => ({ x: dir > 0 ? -300 : 300, opacity: 0, scale: 0.95 }),
};

function ConciergeCarousel({ items, decisions, screenshots, listings, jobId }) {
  const [idx, setIdx] = useState(0);
  const [dir, setDir] = useState(1);

  const goPrev = useCallback(() => { setDir(-1); setIdx(i => Math.max(0, i - 1)); }, []);
  const goNext = useCallback(() => { setDir(1); setIdx(i => Math.min(items.length - 1, i + 1)); }, [items.length]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'ArrowRight') goNext();
      if (e.key === 'ArrowLeft') goPrev();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goNext, goPrev]);

  const item = items[idx];
  if (!item) return null;

  return (
    <div className="cc-carousel">
      <div className="cc-carousel-header">
        <span className="cc-carousel-count">
          {items.length} item{items.length !== 1 ? 's' : ''} live
        </span>
        {items.length > 1 && (
          <div className="pw-carousel-dots">
            {items.map((_, i) => (
              <button
                key={i}
                className={`pw-dot ${i === idx ? 'pw-dot-active' : ''}`}
                onClick={() => { setDir(i > idx ? 1 : -1); setIdx(i); }}
              />
            ))}
          </div>
        )}
      </div>

      <div className="cc-stage">
        {items.length > 1 && idx > 0 && (
          <motion.button className="pw-carousel-arrow pw-arrow-left" onClick={goPrev}
            whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }}>
            <ChevronLeft size={20} />
          </motion.button>
        )}

        <AnimatePresence mode="wait" custom={dir}>
          <motion.div
            key={item.item_id}
            className="cc-stage-slide"
            custom={dir}
            variants={slideVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.4, ease: EASE }}
          >
            <ConciergeSlide
              item={item}
              decision={decisions?.[item.item_id]}
              screenshots={screenshots}
              listings={listings}
              jobId={jobId}
            />
          </motion.div>
        </AnimatePresence>

        {items.length > 1 && idx < items.length - 1 && (
          <motion.button className="pw-carousel-arrow pw-arrow-right" onClick={goNext}
            whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }}>
            <ChevronRight size={20} />
          </motion.button>
        )}
      </div>
    </div>
  );
}

// ── Items Ready to Sell ──────────────────────────────────────────────────────

function ItemsReadyList({ items, decisions, postingStatus, onItemClick }) {
  return (
    <motion.div
      className="conc-items-list"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
    >
      {items.map((item, i) => {
        const decision = decisions?.[item.item_id];
        const heroImg = item.hero_frame_paths?.[0];
        const platforms = Object.keys(postingStatus || {})
          .filter(k => k.startsWith(item.item_id))
          .map(k => k.split(':')[1]);

        return (
          <motion.div
            key={item.item_id}
            className="conc-item-card glass-card"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
            whileHover={{ y: -2 }}
            onClick={() => onItemClick?.(item)}
          >
            <div className="conc-item-card-img">
              {heroImg
                ? <img src={heroImg} alt={item.name_guess} />
                : <Package size={24} style={{ opacity: 0.3 }} />
              }
            </div>
            <div className="conc-item-card-body">
              <h4>{item.name_guess}</h4>
              <div className="conc-item-card-meta">
                <span className="conc-item-condition">{item.condition || 'Used'}</span>
                {decision && (
                  <span className="conc-item-route">
                    {decision.best_route?.replace(/_/g, ' ')}
                  </span>
                )}
              </div>
              {platforms.length > 0 && (
                <div className="conc-item-platforms">
                  {platforms.map(p => (
                    <span key={p} className="conc-platform-pill" style={{ background: PLATFORM_META[p]?.color || '#999' }}>
                      {PLATFORM_META[p]?.label || p}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="conc-item-card-value">
              {decision && <span>${decision.estimated_best_value || 0}</span>}
              <ExternalLink size={14} style={{ opacity: 0.4, marginTop: 4 }} />
            </div>
          </motion.div>
        );
      })}
    </motion.div>
  );
}

// ── Main Concierge Page ──────────────────────────────────────────────────────

// ── Concierge Polling Hook ────────────────────────────────────────────────────

function useConciergePolling(jobId) {
  const [polling, setPolling] = useState(false);
  const [remaining, setRemaining] = useState(90);
  const [agentCount, setAgentCount] = useState(0);
  const [activity, setActivity] = useState([]);
  const startedRef = useRef(false);
  const intervalRef = useRef(null);

  const start = useCallback(async () => {
    if (!jobId || startedRef.current) return;
    startedRef.current = true;
    try {
      const BASE = window.location.origin || '';
      const r = await fetch(`${BASE}/api/jobs/${jobId}/start-concierge`, { method: 'POST' });
      if (r.ok) {
        const data = await r.json();
        setPolling(true);
        setRemaining(data.remaining_s || 90);
        setAgentCount(data.items || 0);
      }
    } catch (err) {
      console.error('Failed to start concierge polling:', err);
    }
  }, [jobId]);

  const stop = useCallback(async () => {
    if (!jobId) return;
    startedRef.current = false;
    setPolling(false);
    try {
      const BASE = window.location.origin || '';
      await fetch(`${BASE}/api/jobs/${jobId}/stop-concierge`, { method: 'POST' });
    } catch { /* best-effort */ }
    if (intervalRef.current) clearInterval(intervalRef.current);
  }, [jobId]);

  // Poll status every second for countdown
  useEffect(() => {
    if (!polling || !jobId) return;
    intervalRef.current = setInterval(async () => {
      try {
        const BASE = window.location.origin || '';
        const r = await fetch(`${BASE}/api/jobs/${jobId}/concierge-status`);
        if (r.ok) {
          const data = await r.json();
          setRemaining(Math.round(data.remaining_s));
          setAgentCount(data.agents || 0);
          if (!data.running) {
            setPolling(false);
            startedRef.current = false;
          }
        }
      } catch { /* ignore */ }
    }, 2000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [polling, jobId]);

  const addActivity = useCallback((msg) => {
    setActivity(prev => [...prev.slice(-19), { text: msg, ts: Date.now() }]);
  }, []);

  return { polling, remaining, agentCount, activity, addActivity, start, stop };
}

// ── Live Activity Feed ───────────────────────────────────────────────────────

function ActivityFeed({ activity }) {
  const ref = useRef(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' });
  }, [activity]);

  if (!activity.length) return null;

  return (
    <div className="conc-activity-feed" ref={ref}>
      {activity.map((a, i) => (
        <motion.div
          key={`${a.ts}-${i}`}
          className="conc-activity-item"
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.2 }}
        >
          <span className="conc-activity-dot" />
          <span>{a.text}</span>
        </motion.div>
      ))}
    </div>
  );
}

// ── Main Concierge Page ──────────────────────────────────────────────────────

export default function ConciergePage({
  items, decisions, listings, threads, postingStatus,
  screenshots, jobId, onSendReply, send,
}) {
  const [view, setView] = useState('hero');
  const [selectedItem, setSelectedItem] = useState(null);
  const concierge = useConciergePolling(jobId);

  // Auto-start polling when concierge page mounts
  useEffect(() => {
    concierge.start();
    return () => { concierge.stop(); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Listen for concierge events from the WebSocket
  useEffect(() => {
    const handler = (e) => {
      try {
        const msg = e.detail || {};
        if (msg.type === 'concierge:message_received') {
          concierge.addActivity(`New message from buyer: "${msg.data?.buyer_message?.slice(0, 60)}..."`);
        } else if (msg.type === 'concierge:reply_sent') {
          concierge.addActivity(`Auto-replied: "${msg.data?.reply?.slice(0, 60)}..."`);
        } else if (msg.type === 'concierge:started') {
          concierge.addActivity(`FB inbox monitoring started for ${msg.data?.items || 0} items`);
        } else if (msg.type === 'concierge:stopped') {
          concierge.addActivity('Inbox monitoring stopped');
        }
      } catch { /* ignore parse errors */ }
    };
    window.addEventListener('ws-event', handler);
    return () => window.removeEventListener('ws-event', handler);
  }, [concierge]);

  const totalValue = useMemo(() => {
    return (items || []).reduce((sum, item) => {
      const d = decisions?.[item.item_id];
      return sum + (d?.estimated_best_value || d?.winning_bid?.estimated_value || 0);
    }, 0);
  }, [items, decisions]);

  const platformCount = useMemo(() => {
    const platforms = new Set();
    Object.keys(postingStatus || {}).forEach(k => {
      const parts = k.split(':');
      if (parts[1]) platforms.add(parts[1]);
    });
    return platforms.size || 1;
  }, [postingStatus]);

  const threadCount = useMemo(() => {
    return (threads || []).length;
  }, [threads]);

  return (
    <motion.div
      className="conc-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, filter: 'blur(4px)' }}
      transition={{ duration: 0.5, ease: EASE }}
    >
      <AnimatePresence mode="wait">
        {view === 'hero' && (
          <motion.div
            key="hero"
            className="conc-hero"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.4, ease: EASE }}
          >
            <motion.div
              className="conc-hero-icon"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', damping: 15, stiffness: 200, delay: 0.1 }}
            >
              <SwarmaLogo size={48} />
            </motion.div>

            <motion.h1
              className="conc-hero-title"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.2, ease: EASE }}
            >
              Your items are live
            </motion.h1>

            <motion.p
              className="conc-hero-subtitle"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.35, ease: EASE }}
            >
              SwarmSell agents posted your items across {platformCount} marketplace{platformCount !== 1 ? 's' : ''}
            </motion.p>

            {/* ── Concierge Polling Status Bar ── */}
            {concierge.polling && (
              <motion.div
                className="conc-polling-bar"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.4 }}
              >
                <div className="conc-polling-indicator">
                  <span className="conc-polling-dot pulse" />
                  <span>Monitoring FB Marketplace inbox</span>
                </div>
                <div className="conc-polling-timer">
                  <span className="conc-timer-value">{concierge.remaining}s</span>
                  <span className="conc-timer-label">remaining</span>
                </div>
                <div className="conc-polling-agents">
                  <span>{concierge.agentCount} agent{concierge.agentCount !== 1 ? 's' : ''} watching</span>
                </div>
              </motion.div>
            )}

            <motion.div
              className="conc-stats"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.5, ease: EASE }}
            >
              <div className="conc-stat glass-card">
                <span className="conc-stat-value">{(items || []).length}</span>
                <span className="conc-stat-label">Items</span>
              </div>
              <div className="conc-stat glass-card">
                <span className="conc-stat-value">{platformCount}</span>
                <span className="conc-stat-label">Platforms</span>
              </div>
              <div className="conc-stat glass-card">
                <span className="conc-stat-value">${Math.round(totalValue)}</span>
                <span className="conc-stat-label">Est. Value</span>
              </div>
              <div className="conc-stat glass-card">
                <span className="conc-stat-value">{threadCount}</span>
                <span className="conc-stat-label">Chats</span>
              </div>
            </motion.div>

            <motion.div
              className="conc-actions"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.65, ease: EASE }}
            >
              <button className="conc-action-btn btn-glass conc-action-primary" onClick={() => setView('listings')}>
                <Eye size={18} />
                <span>View Listings</span>
              </button>
              <button className="conc-action-btn btn-glass" onClick={() => setView('items')}>
                <Package size={18} />
                <span>Items Ready</span>
              </button>
            </motion.div>

            {/* ── Live Activity Feed ── */}
            <ActivityFeed activity={concierge.activity} />
          </motion.div>
        )}

        {view === 'listings' && (
          <motion.div
            key="listings"
            className="conc-view-wrap"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="conc-view-header">
              <button className="conc-back-btn btn-glass" onClick={() => setView('hero')}>
                <ChevronLeft size={14} /> Back
              </button>
              <h2>Your Listings</h2>
              {concierge.polling && (
                <div className="cc-header-status">
                  <span className="cc-live-dot" />
                  <span>{concierge.remaining}s</span>
                </div>
              )}
            </div>
            <ConciergeCarousel
              items={items || []}
              decisions={decisions}
              screenshots={screenshots}
              listings={listings}
              jobId={jobId}
            />
          </motion.div>
        )}

        {view === 'items' && (
          <motion.div
            key="items"
            className="conc-view-wrap"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="conc-view-header">
              <button className="conc-back-btn btn-glass" onClick={() => setView('hero')}>
                <ChevronLeft size={14} /> Back
              </button>
              <h2>Items Ready to Sell</h2>
            </div>
            <ItemsReadyList
              items={items || []}
              decisions={decisions}
              postingStatus={postingStatus}
              onItemClick={setSelectedItem}
            />
            <AnimatePresence>
              {selectedItem && (
                <ItemDetailModal
                  item={selectedItem}
                  onClose={() => setSelectedItem(null)}
                />
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
