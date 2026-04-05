import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const MAROON = {
  deep: '#FFF7F0',
  primary: '#EF4444',
  mid: '#FFFFFF',
  bright: '#FFF1E6',
  glow: '#E7E5E4',
  gold: '#D97706',
  goldLight: '#F59E0B',
};

const BRANCHES = [
  { id: 'facebook', label: 'Marketplace', xPct: 50, yPct: 24, delay: 0.35 },
];

function PlatformLogo({ id, x, y }) {
  if (id === 'facebook') {
    return (
      <text x={x} y={y + 1} textAnchor="middle" dominantBaseline="central"
        fontSize="22" fontWeight="300" fontFamily="'Helvetica Neue', Helvetica, Arial, sans-serif" fill="#fff">
        f
      </text>
    );
  }
  return null;
}

function Particles({ cx, cy, phase }) {
  const particles = useRef(
    Array.from({ length: 18 }, (_, i) => ({
      angle: (i / 18) * Math.PI * 2 + (Math.random() - 0.5) * 0.3,
      dist: 60 + Math.random() * 120,
      size: 1.5 + Math.random() * 2.5,
      delay: Math.random() * 0.3,
      duration: 0.8 + Math.random() * 0.6,
    }))
  ).current;

  return particles.map((p, i) => (
    <motion.circle
      key={i}
      cx={cx} cy={cy}
      r={p.size}
      fill={MAROON.glow}
      initial={{ opacity: 0, x: 0, y: 0 }}
      animate={phase !== 'burst' ? {
        opacity: [0, 0.9, 0],
        x: Math.cos(p.angle) * p.dist,
        y: Math.sin(p.angle) * p.dist,
      } : {}}
      transition={{ duration: p.duration, delay: p.delay, ease: 'easeOut' }}
    />
  ));
}

export default function ExecuteRouteAnimation({ onComplete }) {
  const [phase, setPhase] = useState('burst');
  const containerRef = useRef(null);
  const [dims, setDims] = useState({ w: 1000, h: 600 });

  useEffect(() => {
    if (containerRef.current) {
      const r = containerRef.current.getBoundingClientRect();
      setDims({ w: r.width, h: r.height });
    }
  }, []);

  useEffect(() => {
    const t1 = setTimeout(() => setPhase('branches'), 400);
    const t2 = setTimeout(() => setPhase('glow'), 1200);
    const t3 = setTimeout(() => onComplete(), 4600);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, [onComplete]);

  const cx = dims.w / 2;
  const cy = dims.h * 0.55;

  return (
    <motion.div
      ref={containerRef}
      className="exec-anim-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
    >
      <svg
        className="exec-anim-svg"
        viewBox={`0 0 ${dims.w} ${dims.h}`}
        preserveAspectRatio="none"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      >
        <defs>
          <radialGradient id="exec-center-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={MAROON.glow} stopOpacity="0.4" />
            <stop offset="100%" stopColor={MAROON.deep} stopOpacity="0" />
          </radialGradient>
          <linearGradient id="exec-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={MAROON.bright} />
            <stop offset="100%" stopColor={MAROON.primary} />
          </linearGradient>
          <linearGradient id="exec-grad-gold" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={MAROON.gold} />
            <stop offset="100%" stopColor={MAROON.goldLight} />
          </linearGradient>
          {BRANCHES.map((b, i) => {
            const ex = dims.w * (b.xPct / 100);
            return (
              <linearGradient key={b.id} id={`exec-line-grad-${i}`}
                x1={cx < ex ? '0%' : '100%'} y1="100%" x2={cx < ex ? '100%' : '0%'} y2="0%">
                <stop offset="0%" stopColor={MAROON.bright} />
                <stop offset="50%" stopColor={MAROON.glow} />
                <stop offset="100%" stopColor={MAROON.mid} />
              </linearGradient>
            );
          })}
          <filter id="exec-glow-filter">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="exec-soft-glow">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Ambient center glow */}
        <motion.circle
          cx={cx} cy={cy} r="180"
          fill="url(#exec-center-glow)"
          initial={{ opacity: 0, scale: 0.5 }}
          animate={{ opacity: [0, 0.6, 0.35], scale: [0.5, 1.3, 1.1] }}
          transition={{ duration: 1.2, ease: 'easeOut' }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />

        {/* Particles */}
        <Particles cx={cx} cy={cy} phase={phase} />

        {/* Branch curves + marketplace endpoints */}
        {BRANCHES.map((b, i) => {
          const ex = dims.w * (b.xPct / 100);
          const ey = dims.h * (b.yPct / 100);
          const cpx1 = cx + (ex - cx) * 0.15;
          const cpy1 = cy - 30;
          const cpx2 = cx + (ex - cx) * 0.7;
          const cpy2 = ey + 60;

          return (
            <g key={b.id}>
              {/* Glow line behind the stroke */}
              <motion.path
                d={`M${cx},${cy} C${cpx1},${cpy1} ${cpx2},${cpy2} ${ex},${ey}`}
                fill="none"
                stroke={MAROON.glow}
                strokeWidth="6"
                strokeLinecap="round"
                filter="url(#exec-soft-glow)"
                initial={{ pathLength: 0, opacity: 0 }}
                animate={phase !== 'burst' ? { pathLength: 1, opacity: 0.3 } : {}}
                transition={{ duration: 0.65, delay: b.delay, ease: 'easeOut' }}
              />
              {/* Main curve stroke */}
              <motion.path
                d={`M${cx},${cy} C${cpx1},${cpy1} ${cpx2},${cpy2} ${ex},${ey}`}
                fill="none"
                stroke={`url(#exec-line-grad-${i})`}
                strokeWidth="2.5"
                strokeLinecap="round"
                initial={{ pathLength: 0, opacity: 0 }}
                animate={phase !== 'burst' ? { pathLength: 1, opacity: 1 } : {}}
                transition={{ duration: 0.65, delay: b.delay, ease: 'easeOut' }}
              />

              {/* Outer ring glow */}
              <motion.circle
                cx={ex} cy={ey} r="30"
                fill="none" stroke={MAROON.mid} strokeWidth="1.5"
                filter="url(#exec-soft-glow)"
                initial={{ scale: 0, opacity: 0 }}
                animate={phase === 'glow' ? { scale: 1, opacity: 0.6 } : {}}
                transition={{ duration: 0.4, delay: b.delay + 0.1, type: 'spring', stiffness: 200, damping: 20 }}
                style={{ transformOrigin: `${ex}px ${ey}px` }}
              />
              {/* Filled circle */}
              <motion.circle
                cx={ex} cy={ey} r="26"
                fill={MAROON.primary}
                stroke={MAROON.mid}
                strokeWidth="1.5"
                initial={{ scale: 0, opacity: 0 }}
                animate={phase === 'glow' ? { scale: 1, opacity: 1 } : {}}
                transition={{ duration: 0.35, delay: b.delay + 0.1, type: 'spring', stiffness: 260, damping: 18 }}
                style={{ transformOrigin: `${ex}px ${ey}px` }}
              />
              {/* Double pulse ring */}
              <motion.circle
                cx={ex} cy={ey} r="26"
                fill="none" stroke={MAROON.glow} strokeWidth="2"
                initial={{ scale: 1, opacity: 0 }}
                animate={phase === 'glow' ? { scale: [1, 2.5], opacity: [0.7, 0] } : {}}
                transition={{ duration: 0.8, delay: b.delay + 0.15 }}
                style={{ transformOrigin: `${ex}px ${ey}px` }}
              />
              <motion.circle
                cx={ex} cy={ey} r="26"
                fill="none" stroke={MAROON.bright} strokeWidth="1"
                initial={{ scale: 1, opacity: 0 }}
                animate={phase === 'glow' ? { scale: [1, 3.2], opacity: [0.4, 0] } : {}}
                transition={{ duration: 1, delay: b.delay + 0.25 }}
                style={{ transformOrigin: `${ex}px ${ey}px` }}
              />

              {/* Platform logo */}
              <motion.g
                initial={{ opacity: 0, scale: 0.5 }}
                animate={phase === 'glow' ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.5 }}
                transition={{ duration: 0.25, delay: b.delay + 0.2 }}
                style={{ transformOrigin: `${ex}px ${ey}px` }}
              >
                <PlatformLogo id={b.id} x={ex} y={ey} />
              </motion.g>

              {/* Platform label */}
              <motion.text
                x={ex} y={ey + 46}
                textAnchor="middle" fill="rgba(255,255,255,0.8)"
                fontSize="12" fontWeight="600"
                fontFamily="Inter, -apple-system, sans-serif"
                letterSpacing="1"
                initial={{ opacity: 0, y: ey + 50 }}
                animate={phase === 'glow' ? { opacity: 0.85, y: ey + 46 } : { opacity: 0 }}
                transition={{ duration: 0.35, delay: b.delay + 0.3 }}
              >
                {b.label.toUpperCase()}
              </motion.text>
            </g>
          );
        })}

        {/* Center hub - outer shimmer ring */}
        <motion.circle
          cx={cx} cy={cy} r="32"
          fill="none" stroke={MAROON.gold} strokeWidth="1"
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: [0, 1.1, 1], opacity: [0, 0.6, 0.3] }}
          transition={{ duration: 0.5, delay: 0.1 }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />
        {/* Center hub - main circle */}
        <motion.circle
          cx={cx} cy={cy} r="28"
          fill="url(#exec-grad)"
          filter="url(#exec-glow-filter)"
          initial={{ scale: 0 }}
          animate={{ scale: phase === 'burst' ? [0, 1.5, 1] : 1 }}
          transition={{ duration: 0.4, ease: [0.34, 1.56, 0.64, 1] }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />
        {/* Center pulse rings */}
        <motion.circle
          cx={cx} cy={cy} r="28"
          fill="none" stroke={MAROON.glow} strokeWidth="2.5"
          initial={{ scale: 1, opacity: 0.9 }}
          animate={{ scale: [1, 4], opacity: [0.8, 0] }}
          transition={{ duration: 1.1, delay: 0.1 }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />
        <motion.circle
          cx={cx} cy={cy} r="28"
          fill="none" stroke={MAROON.mid} strokeWidth="1.5"
          initial={{ scale: 1, opacity: 0.6 }}
          animate={{ scale: [1, 5.5], opacity: [0.5, 0] }}
          transition={{ duration: 1.5, delay: 0.2 }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />
        {/* Lightning icon */}
        <motion.text
          x={cx} y={cy + 1}
          textAnchor="middle" dominantBaseline="central"
          fontSize="22" fill="#fff"
          initial={{ opacity: 0, scale: 0.5 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2, duration: 0.3, type: 'spring', stiffness: 300, damping: 15 }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        >
          ⚡
        </motion.text>
      </svg>

      {/* Bottom label */}
      <motion.div
        className="exec-anim-label"
        initial={{ opacity: 0, y: 20 }}
        animate={phase === 'glow' ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
        transition={{ delay: 0.25, duration: 0.4 }}
      >
        Posting to marketplaces…
      </motion.div>
    </motion.div>
  );
}
