import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ChevronLeft, ChevronRight, MessageSquare, Send, Star, MapPin, Heart, Share2, ShoppingCart, Tag, Truck, Shield, Clock, User, ThumbsUp, Eye } from 'lucide-react';

const PLATFORMS = [
  { id: 'facebook', label: 'Facebook Marketplace', color: '#1877f2', accent: '#1877f2' },
];

const CHAT_SCENARIOS = {
  facebook: [
    { delay: 1000, sender: 'buyer', name: 'Sarah M.', text: "Is this available?" },
    { delay: 2500, sender: 'seller', text: "Yes it is! Are you in the area for pickup?" },
    { delay: 4000, sender: 'buyer', name: 'Sarah M.', text: "I'm about 15 min away. Can I come today?" },
    { delay: 5800, sender: 'seller', text: "Sure! I'm free after 3pm. I'll send you the address." },
    { delay: 7500, sender: 'buyer', name: 'Sarah M.', text: "Perfect, see you then! 🙂" },
  ],
};

function formatPrice(price) {
  return price?.toFixed(2) || '0.00';
}

/* ─── eBay listing UI ─────────────────────────────────────────── */
function EbayListing({ item, listing }) {
  const price = listing?.price_strategy || 0;
  const title = listing?.title || item?.name_guess || 'Item';
  const desc = listing?.description || '';
  const condition = listing?.condition_summary || item?.condition_label || 'Used';
  const allImages = item?.hero_frame_paths || [];
  const [activeImgIdx, setActiveImgIdx] = useState(0);
  const heroImg = allImages[activeImgIdx] || allImages[0];
  const specs = listing?.specs || item?.likely_specs || {};

  return (
    <div className="sim-ebay">
      <div className="sim-ebay-topbar">
        <span className="sim-ebay-logo">eBay</span>
        <div className="sim-ebay-search">
          <input type="text" value={title.split(' ').slice(0, 3).join(' ')} readOnly />
        </div>
        <div className="sim-ebay-actions">
          <ShoppingCart size={16} />
          <User size={16} />
        </div>
      </div>
      <div className="sim-ebay-breadcrumb">
        Home &gt; Electronics &gt; {title.split(' ').slice(0, 2).join(' ')}
      </div>
      <div className="sim-ebay-body">
        <div className="sim-ebay-gallery">
          <div className="sim-ebay-hero">
            {heroImg
              ? <img src={heroImg} alt={title} />
              : <div className="sim-ebay-placeholder">📷</div>
            }
          </div>
          <div className="sim-ebay-thumbs">
            {allImages.length > 0 ? allImages.map((img, i) => (
              <div key={i} className={`sim-ebay-thumb ${i === activeImgIdx ? 'active' : ''}`}
                onClick={() => setActiveImgIdx(i)}>
                <img src={img} alt="" />
              </div>
            )) : [0, 1, 2].map(i => (
              <div key={i} className={`sim-ebay-thumb ${i === 0 ? 'active' : ''}`}>
                <div className="sim-ebay-thumb-ph" />
              </div>
            ))}
          </div>
        </div>
        <div className="sim-ebay-details">
          <h2 className="sim-ebay-title">{title}</h2>
          <div className="sim-ebay-condition">
            Condition: <strong>{condition}</strong>
          </div>
          <div className="sim-ebay-price">
            US ${formatPrice(price)}
          </div>
          <div className="sim-ebay-shipping">
            <Truck size={13} /> Free shipping
          </div>
          <div className="sim-ebay-buy-row">
            <button className="sim-ebay-buy-btn">Buy It Now</button>
            <button className="sim-ebay-cart-btn">Add to cart</button>
          </div>
          <button className="sim-ebay-offer-btn">Make Offer</button>
          <div className="sim-ebay-seller">
            <Shield size={13} />
            <span>Seller: <strong>swarma_store</strong> (100% positive)</span>
          </div>
          {Object.keys(specs).length > 0 && (
            <div className="sim-ebay-specs">
              <h4>Item specifics</h4>
              {Object.entries(specs).slice(0, 4).map(([k, v]) => (
                <div key={k} className="sim-ebay-spec-row">
                  <span className="sim-ebay-spec-key">{k}</span>
                  <span className="sim-ebay-spec-val">{v}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="sim-ebay-desc">
        <h4>Description</h4>
        <p>{desc || 'No description provided.'}</p>
      </div>
    </div>
  );
}

/* ─── Facebook Marketplace listing UI ─────────────────────────── */
function FacebookListing({ item, listing }) {
  const price = listing?.price_strategy || 0;
  const title = listing?.title || item?.name_guess || 'Item';
  const desc = listing?.description || '';
  const condition = listing?.condition_summary || item?.condition_label || 'Used';
  const allImages = item?.hero_frame_paths || [];
  const [activeImgIdx, setActiveImgIdx] = useState(0);
  const heroImg = allImages[activeImgIdx] || allImages[0];

  return (
    <div className="sim-fb">
      <div className="sim-fb-topbar">
        <span className="sim-fb-logo">marketplace</span>
      </div>
      <div className="sim-fb-body">
        <div className="sim-fb-gallery">
          {heroImg
            ? <img src={heroImg} alt={title} />
            : <div className="sim-fb-placeholder">📷</div>
          }
          {allImages.length > 1 && (
            <div className="sim-fb-gallery-nav">
              <button className="sim-fb-gallery-btn" disabled={activeImgIdx === 0}
                onClick={() => setActiveImgIdx(i => Math.max(0, i - 1))}>
                <ChevronLeft size={16} />
              </button>
              <span className="sim-fb-gallery-count">{activeImgIdx + 1} / {allImages.length}</span>
              <button className="sim-fb-gallery-btn" disabled={activeImgIdx === allImages.length - 1}
                onClick={() => setActiveImgIdx(i => Math.min(allImages.length - 1, i + 1))}>
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>
        <div className="sim-fb-info">
          <div className="sim-fb-price">${formatPrice(price)}</div>
          <h2 className="sim-fb-title">{title}</h2>
          <div className="sim-fb-meta">
            <span><MapPin size={12} /> Local pickup · Listed 1 minute ago</span>
          </div>
          <div className="sim-fb-condition">
            <Tag size={12} /> Condition: {condition}
          </div>
          <div className="sim-fb-action-row">
            <button className="sim-fb-msg-btn">
              <MessageSquare size={14} /> Message Seller
            </button>
            <button className="sim-fb-save-btn">
              <Heart size={14} />
            </button>
            <button className="sim-fb-share-btn">
              <Share2 size={14} />
            </button>
          </div>
          <div className="sim-fb-desc">
            <h4>Details</h4>
            <p>{desc || 'No description provided.'}</p>
          </div>
          <div className="sim-fb-seller">
            <div className="sim-fb-seller-avatar">R</div>
            <div>
              <strong>SwarmSell Store</strong>
              <div className="sim-fb-seller-meta">Joined 2024 · Typically responds within an hour</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Live chat (Facebook — reads from phone buyer thread) ───── */
function LiveChat({ itemId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const chatEndRef = useRef(null);
  const prevCountRef = useRef(0);

  const fetchThread = useCallback(async () => {
    if (!itemId) return;
    try {
      const BASE = window.location.origin || '';
      const r = await fetch(`${BASE}/api/buyer-chat/${itemId}/thread`);
      if (!r.ok) return;
      const thread = await r.json();
      const msgs = (thread.messages || []).map(m => ({
        sender: m.sender, text: m.text, name: m.sender === 'buyer' ? 'Phone Buyer' : undefined,
      }));
      setMessages(msgs);
      if (msgs.length > prevCountRef.current) {
        prevCountRef.current = msgs.length;
      }
    } catch {}
  }, [itemId]);

  useEffect(() => {
    fetchThread();
    const interval = setInterval(fetchThread, 2000);
    return () => clearInterval(interval);
  }, [fetchThread]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(async () => {
    if (!input.trim()) return;
    const text = input.trim();
    setInput('');
    setMessages(prev => [...prev, { sender: 'seller', text }]);
    try {
      const BASE = window.location.origin || '';
      const r = await fetch(`${BASE}/api/buyer-chat/${itemId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, buyer_name: 'Dashboard' }),
      });
      if (r.ok) {
        const thread = await r.json();
        setMessages((thread.messages || []).map(m => ({
          sender: m.sender, text: m.text, name: m.sender === 'buyer' ? 'Phone Buyer' : undefined,
        })));
      }
    } catch {}
  }, [input, itemId]);

  return (
    <div className="sim-chat" style={{ '--platform-color': '#1877f2' }}>
      <div className="sim-chat-header">
        <MessageSquare size={14} />
        <span>Live Chat — Facebook Marketplace</span>
        <span className="sim-chat-badge">{messages.filter(m => m.sender === 'buyer').length}</span>
        <span className="sim-chat-live-dot" />
      </div>
      <div className="sim-chat-body">
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', fontSize: 13, padding: 32 }}>
            Waiting for buyer to message from the phone…
          </div>
        )}
        {messages.map((msg, i) => (
          <motion.div
            key={i}
            className={`sim-chat-msg sim-chat-${msg.sender}`}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
          >
            {msg.sender === 'buyer' && <span className="sim-chat-name">{msg.name || 'Buyer'}</span>}
            <span className="sim-chat-text">{msg.text}</span>
          </motion.div>
        ))}
        <div ref={chatEndRef} />
      </div>
      <div className="sim-chat-input">
        <input
          type="text"
          placeholder="Reply as seller…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
        />
        <button onClick={handleSend}><Send size={14} /></button>
      </div>
    </div>
  );
}

/* ─── Simulated chat (eBay — automated) ────────────────────────── */
function ChatSimulation({ platformId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const chatEndRef = useRef(null);
  const scenario = CHAT_SCENARIOS[platformId] || CHAT_SCENARIOS.facebook;

  useEffect(() => {
    setMessages([]);
    const timers = scenario.map((msg, i) =>
      setTimeout(() => setMessages(prev => [...prev, msg]), msg.delay)
    );
    return () => timers.forEach(clearTimeout);
  }, [platformId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(() => {
    if (!input.trim()) return;
    setMessages(prev => [...prev, { sender: 'seller', text: input.trim(), delay: 0 }]);
    setInput('');
  }, [input]);

  const platform = PLATFORMS.find(p => p.id === platformId);

  return (
    <div className="sim-chat" style={{ '--platform-color': platform?.color }}>
      <div className="sim-chat-header">
        <MessageSquare size={14} />
        <span>Messages — {platform?.label}</span>
        <span className="sim-chat-badge">{messages.filter(m => m.sender === 'buyer').length}</span>
      </div>
      <div className="sim-chat-body">
        {messages.map((msg, i) => (
          <motion.div
            key={i}
            className={`sim-chat-msg sim-chat-${msg.sender}`}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
          >
            {msg.sender === 'buyer' && <span className="sim-chat-name">{msg.name}</span>}
            {msg.sender === 'system' && <span className="sim-chat-name">System</span>}
            <span className="sim-chat-text">{msg.text}</span>
          </motion.div>
        ))}
        <div ref={chatEndRef} />
      </div>
      <div className="sim-chat-input">
        <input
          type="text"
          placeholder="Type a reply…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
        />
        <button onClick={handleSend}><Send size={14} /></button>
      </div>
    </div>
  );
}

/* ─── Main modal ──────────────────────────────────────────────── */
export default function ListingSimulationModal({ item, listing, onClose }) {
  const [platformIdx, setPlatformIdx] = useState(0);
  const [tab, setTab] = useState('listing');
  const platform = PLATFORMS[platformIdx];

  const prev = useCallback(() => setPlatformIdx(i => (i - 1 + PLATFORMS.length) % PLATFORMS.length), []);
  const next = useCallback(() => setPlatformIdx(i => (i + 1) % PLATFORMS.length), []);

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

  return (
    <motion.div className="sim-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <motion.div className="sim-modal" style={{ '--platform-color': platform.color, '--platform-accent': platform.accent }}
        initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.92, opacity: 0 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}>

        <div className="sim-modal-header">
          <button className="sim-nav-btn" onClick={prev}><ChevronLeft size={18} /></button>
          <div className="sim-platform-tabs">
            {PLATFORMS.map((p, i) => (
              <button key={p.id} className={`sim-platform-tab ${i === platformIdx ? 'active' : ''}`}
                style={i === platformIdx ? { borderColor: p.color, color: p.color } : {}}
                onClick={() => setPlatformIdx(i)}>
                {p.label}
              </button>
            ))}
          </div>
          <button className="sim-nav-btn" onClick={next}><ChevronRight size={18} /></button>
          <button className="sim-close-btn" onClick={onClose}><X size={16} /></button>
        </div>

        <div className="sim-tab-bar">
          <button className={`sim-tab ${tab === 'listing' ? 'active' : ''}`} onClick={() => setTab('listing')}>
            <Eye size={13} /> Listing Preview
          </button>
          <button className={`sim-tab ${tab === 'chat' ? 'active' : ''}`} onClick={() => setTab('chat')}>
            <MessageSquare size={13} /> Customer Chat
          </button>
        </div>

        <div className="sim-modal-body">
          <AnimatePresence mode="wait">
            {tab === 'listing' ? (
              <motion.div key={`listing-${platform.id}`} initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} transition={{ duration: 0.2 }}>
                {platform.id === 'facebook' && <FacebookListing item={item} listing={listing} />}
              </motion.div>
            ) : (
              <motion.div key={`chat-${platform.id}`} initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} transition={{ duration: 0.2 }}>
                {platform.id === 'facebook'
                  ? <LiveChat itemId={item?.item_id} />
                  : <ChatSimulation platformId={platform.id} />
                }
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="sim-modal-footer">
          <div className="sim-status-row">
            <span className="sim-status-dot" style={{ background: platform.color }} />
            <span>Live on {platform.label}</span>
          </div>
          <span className="sim-platform-count">{platformIdx + 1} / {PLATFORMS.length}</span>
        </div>
      </motion.div>
    </motion.div>
  );
}
