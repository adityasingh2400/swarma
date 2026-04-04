import { useRef, useEffect } from 'react';
import { useSwarmActivity } from './SwarmActivityProvider';

const MAX_PARTICLES = 150;
const DPR = Math.min(window.devicePixelRatio || 1, 1.5);

const STAGE_HUES = {
  video: 260,
  analysis: 240,
  research: 220,
  decision: 200,
  listing: 270,
};

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function createParticle(w, h) {
  return {
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.3,
    vy: (Math.random() - 0.5) * 0.3,
    radius: Math.random() * 1.5 + 0.5,
    alpha: Math.random() * 0.4 + 0.1,
    hueOffset: (Math.random() - 0.5) * 30,
  };
}

export default function AuroraCanvas() {
  const canvasRef = useRef(null);
  const metricsRef = useSwarmActivity();
  const particlesRef = useRef([]);
  const animRef = useRef(null);
  const sizeRef = useRef({ w: 0, h: 0 });

  useEffect(() => {
    const prefersReduced = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches;
    if (prefersReduced) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    function resize() {
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas.width = w * DPR;
      canvas.height = h * DPR;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      sizeRef.current = { w, h };
    }

    resize();
    window.addEventListener('resize', resize);

    const particles = [];
    const { w, h } = sizeRef.current;
    for (let i = 0; i < MAX_PARTICLES; i++) {
      particles.push(createParticle(w, h));
    }
    particlesRef.current = particles;

    let prevTime = performance.now();

    function draw(now) {
      const dt = Math.min((now - prevTime) / 16.67, 3);
      prevTime = now;

      const { w: cw, h: ch } = sizeRef.current;
      const m = metricsRef?.current || {};
      const activeCount = m.activeCount || 0;
      const byteRate = m.byteRate || 0;
      const stage = m.pipelineStage || 'video';
      const focusId = m.focusedAgentId;

      const baseHue = STAGE_HUES[stage] ?? 260;
      const intensity = Math.min(1, activeCount / 12);
      const pulseSpeed = 0.5 + (byteRate / 100000) * 1.5;

      ctx.clearRect(0, 0, cw, ch);

      const grd = ctx.createRadialGradient(
        cw * 0.5,
        ch * 0.4,
        0,
        cw * 0.5,
        ch * 0.5,
        Math.max(cw, ch) * 0.7,
      );
      grd.addColorStop(
        0,
        `hsla(${baseHue}, 60%, ${8 + intensity * 4}%, ${0.3 + intensity * 0.15})`,
      );
      grd.addColorStop(
        0.5,
        `hsla(${baseHue + 20}, 50%, ${5 + intensity * 2}%, 0.15)`,
      );
      grd.addColorStop(1, 'hsla(0, 0%, 4%, 0)');
      ctx.fillStyle = grd;
      ctx.fillRect(0, 0, cw, ch);

      let focusX = cw * 0.5;
      let focusY = ch * 0.5;

      if (focusId && m.agents) {
        const fa = m.agents.find((a) => a.id === focusId);
        if (fa) {
          focusX = fa.normalizedXY[0] * cw;
          focusY = fa.normalizedXY[1] * ch;
        }
      }

      const pulseFactor =
        1 + Math.sin(now * 0.001 * pulseSpeed) * 0.15 * intensity;

      for (const p of particles) {
        const dxFocus = focusX - p.x;
        const dyFocus = focusY - p.y;
        const distFocus = Math.sqrt(dxFocus * dxFocus + dyFocus * dyFocus) || 1;
        const pullStrength = focusId ? 0.02 * intensity : 0.005;

        p.vx += (dxFocus / distFocus) * pullStrength * dt;
        p.vy += (dyFocus / distFocus) * pullStrength * dt;

        p.vx *= 0.98;
        p.vy *= 0.98;

        const speedCap = 1.5 + intensity * 1.5;
        const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
        if (speed > speedCap) {
          p.vx = (p.vx / speed) * speedCap;
          p.vy = (p.vy / speed) * speedCap;
        }

        p.x += p.vx * dt;
        p.y += p.vy * dt;

        if (p.x < -20) p.x = cw + 20;
        if (p.x > cw + 20) p.x = -20;
        if (p.y < -20) p.y = ch + 20;
        if (p.y > ch + 20) p.y = -20;

        const hue = baseHue + p.hueOffset;
        const r = p.radius * pulseFactor;
        const a = p.alpha * lerp(0.3, 1, intensity);

        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${hue}, 70%, 65%, ${a})`;
        ctx.fill();

        if (r > 1 && intensity > 0.3) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * 3, 0, Math.PI * 2);
          ctx.fillStyle = `hsla(${hue}, 60%, 55%, ${a * 0.15})`;
          ctx.fill();
        }
      }

      if (intensity > 0.2 && m.agents) {
        ctx.strokeStyle = `hsla(${baseHue}, 50%, 60%, ${0.03 * intensity})`;
        ctx.lineWidth = 0.5;
        for (let i = 0; i < particles.length; i++) {
          for (let j = i + 1; j < particles.length; j++) {
            const dx = particles[i].x - particles[j].x;
            const dy = particles[i].y - particles[j].y;
            const dist = dx * dx + dy * dy;
            if (dist < 8000) {
              ctx.beginPath();
              ctx.moveTo(particles[i].x, particles[i].y);
              ctx.lineTo(particles[j].x, particles[j].y);
              ctx.stroke();
            }
          }
        }
      }

      animRef.current = requestAnimationFrame(draw);
    }

    animRef.current = requestAnimationFrame(draw);

    return () => {
      window.removeEventListener('resize', resize);
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [metricsRef]);

  return (
    <canvas
      ref={canvasRef}
      className="aurora-canvas"
      aria-hidden="true"
    />
  );
}
