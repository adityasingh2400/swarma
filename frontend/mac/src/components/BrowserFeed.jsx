import { motion, AnimatePresence } from 'framer-motion';

export default function BrowserFeed({ url, className = '', large = false }) {
  return (
    <div className={`browser-feed ${large ? 'browser-feed-lg' : ''} ${className}`}>
      <AnimatePresence mode="popLayout">
        {url ? (
          <motion.img
            key={url}
            src={url}
            alt=""
            className="browser-feed-img"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          />
        ) : (
          <motion.div
            key="pulse"
            className="browser-feed-pulse"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
