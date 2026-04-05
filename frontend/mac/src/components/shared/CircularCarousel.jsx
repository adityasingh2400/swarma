import { useState, useRef, useEffect, useCallback } from 'react';

const MOBILE_BP = 767;

/**
 * Orbital carousel with dynamic scale/opacity based on distance from front.
 *
 * Props:
 *   items       – array of data objects
 *   renderItem  – (item, index, isActive, isFocused) => ReactNode
 *   onSelect    – optional callback (item, index) when front item is clicked
 *   className   – optional extra class on the container
 */
export default function CircularCarousel({ items, renderItem, onSelect, className = '' }) {
  const containerRef = useRef(null);
  const itemRefs = useRef([]);
  const prevZRef = useRef([]);
  const rafRef = useRef(null);
  const progressRef = useRef(0);
  const [activeIndex, setActiveIndex] = useState(0);
  const [focused, setFocused] = useState(null);
  const [isMobile, setIsMobile] = useState(false);

  /* ── responsive check ── */
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth <= MOBILE_BP);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  /* ── position every item on the elliptical orbit ── */
  const positionItems = useCallback((progress) => {
    const container = containerRef.current;
    if (!container || !items.length) return;

    const { width: w, height: h } = container.getBoundingClientRect();
    const cx = w / 2;
    const cy = h / 2;
    const RX = w * 0.34;
    const RY = h * 0.18;
    const n = items.length;

    for (let i = 0; i < n; i++) {
      const el = itemRefs.current[i];
      if (!el) continue;

      const angle = ((i / n) - progress) * Math.PI * 2;
      const normAngle = ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
      const dist = Math.abs(normAngle > Math.PI ? (2 * Math.PI - normAngle) : normAngle) / Math.PI;

      const x = cx + RX * Math.sin(angle);
      const y = cy - RY * Math.cos(angle);
      const scale = 0.18 + 0.82 * Math.pow(Math.max(0, 1 - dist), 1.4);
      const opacity = Math.max(0.03, Math.pow(Math.max(0, 1 - dist), 1.6));
      const z = Math.round(100 * (1 - dist));

      // GPU-only properties
      el.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%) scale(${scale})`;
      el.style.opacity = String(opacity);

      // only touch zIndex when integer changes
      if (prevZRef.current[i] !== z) {
        prevZRef.current[i] = z;
        el.style.zIndex = String(z);
      }
    }
  }, [items]);

  /* ── animate smoothly to a target progress ── */
  const animateTo = useCallback((targetProgress) => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);

    const start = progressRef.current;
    const startTime = performance.now();
    const duration = 500; // ms

    const tick = (now) => {
      const elapsed = now - startTime;
      const t = Math.min(elapsed / duration, 1);
      // ease-out expo
      const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      const current = start + (targetProgress - start) * eased;
      progressRef.current = current;
      positionItems(current);

      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
  }, [positionItems]);

  /* ── go to index ── */
  const goTo = useCallback((index) => {
    const n = items.length;
    if (!n) return;
    const wrapped = ((index % n) + n) % n;
    setActiveIndex(wrapped);
    animateTo(wrapped / n);
  }, [items.length, animateTo]);

  /* ── scroll-driven (desktop) ── */
  useEffect(() => {
    if (isMobile) return;
    const container = containerRef.current;
    if (!container) return;

    const handleWheel = (e) => {
      e.preventDefault();
      const delta = Math.sign(e.deltaY);
      const n = items.length;
      setActiveIndex(prev => {
        const next = ((prev + delta) % n + n) % n;
        animateTo(next / n);
        return next;
      });
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, [isMobile, items.length, animateTo]);

  /* ── swipe (mobile) ── */
  const touchStart = useRef(0);
  const handleTouchStart = (e) => { touchStart.current = e.touches[0].clientX; };
  const handleTouchEnd = (e) => {
    const dx = e.changedTouches[0].clientX - touchStart.current;
    if (Math.abs(dx) > 48) {
      goTo(activeIndex + (dx > 0 ? -1 : 1));
    }
  };

  /* ── keyboard navigation ── */
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        goTo(activeIndex + 1);
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        goTo(activeIndex - 1);
      } else if (e.key === 'Escape') {
        setFocused(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [activeIndex, goTo]);

  /* ── initial layout ── */
  useEffect(() => {
    prevZRef.current = new Array(items.length).fill(-1);
    positionItems(0);
  }, [items.length, positionItems]);

  /* ── resize handler ── */
  useEffect(() => {
    const onResize = () => positionItems(progressRef.current);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [positionItems]);

  /* ── cleanup ── */
  useEffect(() => {
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, []);

  return (
    <div
      ref={containerRef}
      className={`circular-carousel ${className}`}
      onTouchStart={isMobile ? handleTouchStart : undefined}
      onTouchEnd={isMobile ? handleTouchEnd : undefined}
      role="region"
      aria-label="Carousel"
      aria-roledescription="carousel"
    >
      {items.map((item, i) => (
        <div
          key={item.id ?? i}
          ref={(el) => { itemRefs.current[i] = el; }}
          className={`carousel-card${focused === i ? ' focused' : ''}`}
          onClick={() => {
            if (i === activeIndex) {
              if (onSelect) {
                onSelect(item, i);
              } else {
                setFocused(focused === i ? null : i);
              }
            } else {
              goTo(i);
            }
          }}
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            willChange: 'transform, opacity',
          }}
          role="group"
          aria-roledescription="slide"
          aria-label={`Slide ${i + 1} of ${items.length}`}
        >
          {renderItem(item, i, i === activeIndex, focused === i)}
        </div>
      ))}

      {/* Navigation dots */}
      <div className="carousel-dots">
        {items.map((_, i) => (
          <button
            key={i}
            className={`carousel-dot${i === activeIndex ? ' active' : ''}`}
            onClick={() => goTo(i)}
            aria-label={`Go to slide ${i + 1}`}
          />
        ))}
      </div>
    </div>
  );
}
