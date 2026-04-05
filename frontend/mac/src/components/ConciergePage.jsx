import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Eye, Package, Video, X, ChevronLeft, ChevronRight,
  MessageSquare, Send, Star, Check, ExternalLink,
  ShoppingCart, Tag, Truck, Shield, MapPin, Heart, Share2, User,
} from 'lucide-react';
import SwarmaLogo from './SwarmaLogo';
import IntakePanel from './panels/IntakePanel';
import { PLATFORMS as PLATFORM_IDS } from '../utils/contracts';

const EASE = [0.32, 0.72, 0, 1];

const PLATFORM_META = {
  ebay: { label: 'eBay', color: '#e53238', accent: '#0064d2' },
  facebook: { label: 'Facebook', color: '#1877f2', accent: '#1877f2' },
  mercari: { label: 'Mercari', color: '#4dc9f6', accent: '#4dc9f6' },
  depop: { label: 'Depop', color: '#ff2300', accent: '#ff2300' },
};

function formatPrice(price) {
  return price?.toFixed?.(2) || '0.00';
}

// ── Live Chat (polls real backend) ───────────────────────────────────────────

function LiveConversation({ itemId, jobId, platform }) {
  const [threads, setThreads] = useState([]);
  const [replyText, setReplyText] = useState({});
  const chatEndRef = useRef(null);

  const fetchThreads = useCallback(async () => {
    if (!jobId) return;
    try {
      const BASE = window.location.origin || '';
      const r = await fetch(`${BASE}/api/jobs/${jobId}/inbox`);
      if (!r.ok) return;
      const all = await r.json();
      const filtered = all.filter(t => t.item_id === itemId && (!platform || t.platform === platform));
      setThreads(filtered);
    } catch (err) {
      console.error('Failed to fetch inbox:', err);
    }
  }, [jobId, itemId, platform]);

  useEffect(() => {
    fetchThreads();
    const interval = setInterval(fetchThreads, 3000);
    return () => clearInterval(interval);
  }, [fetchThreads]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
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

  const meta = PLATFORM_META[platform] || PLATFORM_META.ebay;

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
    <div className="conc-conversations" style={{ '--platform-color': meta.color }}>
      {threads.map(thread => {
        const lastMsg = thread.messages?.[thread.messages.length - 1];
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
              <div ref={chatEndRef} />
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

// ── Platform Screenshot / Listing Preview ────────────────────────────────────

function PlatformPreview({ item, platform, screenshot, listing }) {
  if (screenshot) {
    return (
      <div className="conc-screenshot-wrap">
        <img src={screenshot} alt={`${platform} listing`} className="conc-screenshot-img" />
        <div className="conc-screenshot-badge">
          <Check size={10} />
          <span>Live on {PLATFORM_META[platform]?.label || platform}</span>
        </div>
      </div>
    );
  }

  const price = listing?.price_strategy || item?.estimated_value || 0;
  const title = listing?.title || item?.name_guess || 'Item';
  const heroImg = item?.hero_frame_paths?.[0];

  return (
    <div className="conc-listing-preview">
      <div className="conc-listing-hero">
        {heroImg ? <img src={heroImg} alt={title} /> : <div className="conc-listing-placeholder">No image</div>}
      </div>
      <div className="conc-listing-info">
        <h3>{title}</h3>
        <div className="conc-listing-price">${formatPrice(price)}</div>
        <div className="conc-listing-meta">
          <Tag size={12} /> {item?.condition || 'Used'}
          <Truck size={12} style={{ marginLeft: 12 }} /> Free shipping
        </div>
      </div>
    </div>
  );
}

// ── Item Detail Modal ────────────────────────────────────────────────────────

function ItemDetailModal({ item, decisions, screenshots, listings, postingStatus, jobId, onClose, onSendReply }) {
  const postedPlatforms = useMemo(() => {
    if (!postingStatus || !item) return Object.keys(PLATFORM_META);
    const posted = [];
    for (const key of Object.keys(postingStatus)) {
      const [iid, plat] = key.split(':');
      if (iid === item.item_id) posted.push(plat);
    }
    return posted.length > 0 ? posted : Object.keys(PLATFORM_META);
  }, [item, postingStatus]);

  const [platformIdx, setPlatformIdx] = useState(0);
  const [tab, setTab] = useState('listing');
  const platform = postedPlatforms[platformIdx] || 'ebay';
  const meta = PLATFORM_META[platform] || PLATFORM_META.ebay;

  const prev = useCallback(() => setPlatformIdx(i => (i - 1 + postedPlatforms.length) % postedPlatforms.length), [postedPlatforms]);
  const next = useCallback(() => setPlatformIdx(i => (i + 1) % postedPlatforms.length), [postedPlatforms]);

  useEffect(() => { setTab('listing'); }, [platformIdx]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight') next();
      if (e.key === 'ArrowLeft') prev();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, next, prev]);

  const screenshotUrl = screenshots instanceof Map
    ? screenshots.get(`${platform}-listing-${item?.item_id?.slice(0, 6)}`)?.url
    : screenshots?.[`${platform}-listing-${item?.item_id?.slice(0, 6)}`]?.url;

  const decision = decisions?.[item?.item_id];

  return (
    <motion.div
      className="sim-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <motion.div
        className="conc-detail-modal glass-enhanced"
        style={{ '--platform-color': meta.color, '--platform-accent': meta.accent }}
        initial={{ scale: 0.92, opacity: 0, y: 30 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.92, opacity: 0, y: 30 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
      >
        <div className="conc-modal-header">
          <button className="sim-nav-btn" onClick={prev}><ChevronLeft size={18} /></button>
          <div className="conc-platform-tabs">
            {postedPlatforms.map((p, i) => (
              <button
                key={p}
                className={`sim-platform-tab ${i === platformIdx ? 'active' : ''}`}
                style={i === platformIdx ? { borderColor: PLATFORM_META[p]?.color, color: PLATFORM_META[p]?.color } : {}}
                onClick={() => setPlatformIdx(i)}
              >
                {PLATFORM_META[p]?.label || p}
              </button>
            ))}
          </div>
          <button className="sim-nav-btn" onClick={next}><ChevronRight size={18} /></button>
          <button className="sim-close-btn" onClick={onClose}><X size={16} /></button>
        </div>

        <div className="sim-tab-bar">
          <button className={`sim-tab ${tab === 'listing' ? 'active' : ''}`} onClick={() => setTab('listing')}>
            <Eye size={13} /> Listing
          </button>
          <button className={`sim-tab ${tab === 'chat' ? 'active' : ''}`} onClick={() => setTab('chat')}>
            <MessageSquare size={13} /> Conversations
          </button>
        </div>

        <div className="conc-modal-body">
          <AnimatePresence mode="wait">
            {tab === 'listing' ? (
              <motion.div key={`listing-${platform}`} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.2 }}>
                <PlatformPreview item={item} platform={platform} screenshot={screenshotUrl} listing={listings?.[item?.item_id]} />
              </motion.div>
            ) : (
              <motion.div key={`chat-${platform}`} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.2 }}>
                <LiveConversation itemId={item?.item_id} jobId={jobId} platform={platform} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="conc-modal-footer">
          <div className="conc-modal-status">
            <span className="conc-status-dot" style={{ background: meta.color }} />
            <span>Live on {meta.label}</span>
          </div>
          {decision && (
            <span className="conc-modal-value">
              Est. ${decision.estimated_best_value || decision.winning_bid?.estimated_value || 0}
            </span>
          )}
          <span className="conc-modal-counter">{platformIdx + 1} / {postedPlatforms.length}</span>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ── Exploding Nodes (View Listings) ──────────────────────────────────────────

function ExplodingNodes({ items, decisions, screenshots, listings, postingStatus, jobId, onSendReply }) {
  const [selectedItem, setSelectedItem] = useState(null);

  return (
    <>
      <motion.div
        className="conc-nodes-grid"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4 }}
      >
        {items.map((item, i) => {
          const decision = decisions?.[item.item_id];
          const heroImg = item.hero_frame_paths?.[0];
          const platformCount = Object.keys(postingStatus || {}).filter(k => k.startsWith(item.item_id)).length || PLATFORM_IDS.length;

          return (
            <motion.div
              key={item.item_id}
              className="conc-node ide-bubble"
              initial={{ opacity: 0, scale: 0.3, y: 60 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{
                delay: i * 0.1,
                type: 'spring',
                damping: 20,
                stiffness: 200,
              }}
              whileHover={{ scale: 1.05, y: -4 }}
              onClick={() => setSelectedItem(item)}
            >
              <div className="conc-node-img">
                {heroImg
                  ? <img src={heroImg} alt={item.name_guess} />
                  : <Package size={28} style={{ opacity: 0.3 }} />
                }
              </div>
              <div className="conc-node-info">
                <span className="conc-node-name">{item.name_guess}</span>
                <span className="conc-node-meta">
                  {platformCount} platform{platformCount !== 1 ? 's' : ''}
                  {decision && ` · $${decision.estimated_best_value || ''}`}
                </span>
              </div>
              <div className="conc-node-badge">
                <Check size={10} />
              </div>
            </motion.div>
          );
        })}
      </motion.div>

      <AnimatePresence>
        {selectedItem && (
          <ItemDetailModal
            item={selectedItem}
            decisions={decisions}
            screenshots={screenshots}
            listings={listings}
            postingStatus={postingStatus}
            jobId={jobId}
            onClose={() => setSelectedItem(null)}
            onSendReply={onSendReply}
          />
        )}
      </AnimatePresence>
    </>
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

export default function ConciergePage({
  items, decisions, listings, threads, postingStatus,
  screenshots, jobId, onUpload, onSendReply, send,
}) {
  const [view, setView] = useState('hero');
  const [selectedItem, setSelectedItem] = useState(null);

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
    return platforms.size || PLATFORM_IDS.length;
  }, [postingStatus]);

  const threadCount = useMemo(() => {
    return (threads || []).length;
  }, [threads]);

  const handleUpload = useCallback((file, url) => {
    onUpload?.(file, url);
    setView('hero');
  }, [onUpload]);

  if (view === 'film') {
    return (
      <motion.div
        key="film-another"
        className="conc-film-wrap"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <motion.button
          className="conc-back-btn btn-glass"
          onClick={() => setView('hero')}
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.2 }}
        >
          <ChevronLeft size={14} />
          Back to Concierge
        </motion.button>
        <IntakePanel onUpload={handleUpload} fullscreen />
      </motion.div>
    );
  }

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
              Swarma agents posted your items across {platformCount} marketplace{platformCount !== 1 ? 's' : ''}
            </motion.p>

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
              <button className="conc-action-btn btn-glass" onClick={() => setView('film')}>
                <Video size={18} />
                <span>Film Another</span>
              </button>
            </motion.div>
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
            </div>
            <ExplodingNodes
              items={items || []}
              decisions={decisions}
              screenshots={screenshots}
              listings={listings}
              postingStatus={postingStatus}
              jobId={jobId}
              onSendReply={onSendReply}
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
                  decisions={decisions}
                  screenshots={screenshots}
                  listings={listings}
                  postingStatus={postingStatus}
                  jobId={jobId}
                  onClose={() => setSelectedItem(null)}
                  onSendReply={onSendReply}
                />
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
