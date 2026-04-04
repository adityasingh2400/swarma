import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Send, Star, ChevronDown, ChevronUp } from 'lucide-react';
import Badge from '../shared/Badge';

const DEMO_THREADS = [
  {
    thread_id: 't1',
    item_id: 'demo-1',
    platform: 'ebay',
    buyer_handle: 'tech_deals_23',
    seriousness_score: 0.9,
    current_offer: 750,
    suggested_reply: "I appreciate the offer! The lowest I can go is $770 since it includes all accessories. Let me know!",
    is_winning: true,
    resolved: false,
    messages: [
      { sender: 'buyer', text: "Hi, is this still available?", timestamp: '2026-03-20T10:00:00Z' },
      { sender: 'seller', text: "Yes! Still available and in great condition.", timestamp: '2026-03-20T10:05:00Z' },
      { sender: 'buyer', text: "Would you accept $750? I can pay today.", timestamp: '2026-03-20T10:10:00Z' },
    ],
  },
  {
    thread_id: 't2',
    item_id: 'demo-1',
    platform: 'mercari',
    buyer_handle: 'sarah_m_shop',
    seriousness_score: 0.5,
    current_offer: 680,
    suggested_reply: "Thanks for your interest! I could do $720 — this model is in excellent condition with original accessories.",
    is_winning: false,
    resolved: false,
    messages: [
      { sender: 'buyer', text: "Is there any flexibility on price?", timestamp: '2026-03-20T11:00:00Z' },
    ],
  },
  {
    thread_id: 't3',
    item_id: 'demo-1',
    platform: 'facebook',
    buyer_handle: 'Mike Johnson',
    seriousness_score: 0.2,
    current_offer: null,
    suggested_reply: "Yes, still available! Would you like more details or photos?",
    is_winning: false,
    resolved: false,
    messages: [
      { sender: 'buyer', text: "Still available?", timestamp: '2026-03-20T12:00:00Z' },
    ],
  },
];

function seriousnessLabel(score) {
  if (score >= 0.7) return 'high';
  if (score >= 0.4) return 'medium';
  return 'low';
}

export default function UnifiedInbox({ threads: liveThreads, onSendReply }) {
  const [expandedId, setExpandedId] = useState(null);
  const [replyText, setReplyText] = useState({});

  const threads = liveThreads?.length > 0 ? liveThreads : [];

  if (threads.length === 0) {
    return (
      <div className="unified-inbox" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 20px', color: 'var(--text-tertiary)' }}>
        <MessageSquare size={36} style={{ marginBottom: 12, opacity: 0.4 }} />
        <p style={{ fontSize: 14, marginBottom: 4 }}>No buyer conversations yet</p>
        <p style={{ fontSize: 12, opacity: 0.6 }}>Conversations will appear here after listings go live</p>
      </div>
    );
  }

  const handleExpand = useCallback((id) => {
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const handleSend = useCallback((threadId) => {
    const text = replyText[threadId];
    if (!text?.trim()) return;
    onSendReply?.(threadId, text);
    setReplyText((prev) => ({ ...prev, [threadId]: '' }));
  }, [replyText, onSendReply]);

  const useSuggested = useCallback((threadId, suggestion) => {
    setReplyText((prev) => ({ ...prev, [threadId]: suggestion }));
  }, []);

  return (
    <div className="unified-inbox">
      {threads.map((thread, index) => {
        const isExpanded = expandedId === thread.thread_id;
        const lastMessage = thread.messages?.[thread.messages.length - 1]?.text || '';
        const sLabel = seriousnessLabel(thread.seriousness_score);

        return (
          <motion.div
            key={thread.thread_id}
            className={`ui-thread ${thread.is_winning ? 'best-buyer' : ''}`}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.08 }}
          >
            <div className="ui-thread-header" onClick={() => handleExpand(thread.thread_id)}>
              <Badge platform={thread.platform} />
              <div className="ui-buyer-info">
                <div className="ui-buyer-name">
                  {thread.buyer_handle}
                  {thread.is_winning && (
                    <Star
                      size={12}
                      fill="var(--success)"
                      color="var(--success)"
                      style={{ marginLeft: 6, verticalAlign: 'middle' }}
                    />
                  )}
                </div>
                <div className="ui-last-message">{lastMessage}</div>
              </div>
              {thread.current_offer != null && (
                <div className="ui-offer">
                  <div className="ui-offer-amount" style={{
                    color: thread.is_winning ? 'var(--success)' : 'var(--text-primary)',
                    fontFamily: 'var(--font-mono)',
                  }}>
                    ${thread.current_offer}
                  </div>
                  <div className="ui-offer-label">offer</div>
                </div>
              )}
              <Badge variant={
                sLabel === 'high' ? 'success' :
                sLabel === 'medium' ? 'warning' : 'neutral'
              }>
                {sLabel}
              </Badge>
              {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </div>

            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  className="ui-thread-expanded"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="ui-messages">
                    {(thread.messages || []).map((msg, i) => (
                      <div key={i} className={`ui-message ${msg.sender}`}>
                        {msg.text}
                      </div>
                    ))}
                  </div>

                  {thread.suggested_reply && (
                    <motion.div
                      style={{
                        padding: '8px 12px',
                        background: 'var(--primary-dim)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: 12,
                        color: 'var(--text-secondary)',
                        marginBottom: 8,
                        cursor: 'pointer',
                        border: '1px solid rgba(99,102,241,0.2)',
                      }}
                      onClick={() => useSuggested(thread.thread_id, thread.suggested_reply)}
                      whileHover={{ scale: 1.01 }}
                    >
                      <span style={{ color: 'var(--primary)', fontWeight: 600, fontSize: 10, display: 'block', marginBottom: 2 }}>
                        Suggested Reply — click to use
                      </span>
                      {thread.suggested_reply}
                    </motion.div>
                  )}

                  <div className="ui-reply-box">
                    <input
                      className="ui-reply-input"
                      placeholder="Type a reply..."
                      value={replyText[thread.thread_id] || ''}
                      onChange={(e) => setReplyText((prev) => ({ ...prev, [thread.thread_id]: e.target.value }))}
                      onKeyDown={(e) => e.key === 'Enter' && handleSend(thread.thread_id)}
                    />
                    <button
                      className="ui-send-btn"
                      onClick={() => handleSend(thread.thread_id)}
                    >
                      <Send size={14} />
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        );
      })}
    </div>
  );
}
