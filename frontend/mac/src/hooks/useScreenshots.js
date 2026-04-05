import { useState, useEffect, useRef, useCallback } from 'react';
import {
  SCREENSHOT_FRAME_VERSION,
  SCREENSHOT_AGENT_ID_BYTES,
  SCREENSHOT_HEADER_BYTES,
} from '../utils/contracts';
import { swarmaFe } from '../utils/debugLog';

const decoder = new TextDecoder('utf-8', { fatal: false });

function parseFrame(arrayBuffer) {
  if (!arrayBuffer || arrayBuffer.byteLength < SCREENSHOT_HEADER_BYTES) return null;

  const view = new DataView(arrayBuffer);
  if (view.getUint8(0) !== SCREENSHOT_FRAME_VERSION) return null;

  const idSlice = new Uint8Array(arrayBuffer, 1, SCREENSHOT_AGENT_ID_BYTES);
  const agentId = decoder.decode(idSlice).replace(/\0/g, '').trim();
  if (!agentId) return null;

  const timestamp = view.getUint32(1 + SCREENSHOT_AGENT_ID_BYTES, false);

  const jpeg = new Uint8Array(arrayBuffer, SCREENSHOT_HEADER_BYTES);
  if (jpeg.length === 0) return null;

  const blob = new Blob([jpeg], { type: 'image/jpeg' });
  return { agentId, timestamp, blob };
}

/** Cap UI refresh rate per agent so blob URL swaps don’t thrash React / <img> (visible flicker). */
const SCREENSHOT_UI_MIN_MS = 160;

export function useScreenshots(jobId) {
  const [screenshots, setScreenshots] = useState(new Map());
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const urlMapRef = useRef(new Map());
  const lastUiApplyRef = useRef(new Map());

  const cleanup = useCallback(() => {
    urlMapRef.current.forEach((url) => URL.revokeObjectURL(url));
    urlMapRef.current.clear();
    setScreenshots(new Map());
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let alive = true;

    function connect() {
      if (!alive) return;

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host || 'localhost:8080';
      const url = `${protocol}//${host}/ws/${jobId}/screenshots`;
      swarmaFe('useScreenshots', 'connect_attempt', { jobId, url });
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;
      let frameCount = 0;

      ws.onopen = () => {
        if (!alive) return;
        swarmaFe('useScreenshots', 'open', { jobId });
        setConnected(true);
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      ws.onmessage = (ev) => {
        if (!alive || !(ev.data instanceof ArrayBuffer)) return;

        const frame = parseFrame(ev.data);
        if (!frame) return;

        frameCount += 1;
        if (frameCount <= 2 || frameCount % 30 === 0) {
          swarmaFe('useScreenshots', 'frame', {
            jobId,
            n: frameCount,
            agentId: frame.agentId,
            jpegBytes: frame.blob?.size,
          });
        }

        const now = Date.now();
        const lastApply = lastUiApplyRef.current.get(frame.agentId);
        if (lastApply != null && now - lastApply < SCREENSHOT_UI_MIN_MS) {
          return;
        }
        lastUiApplyRef.current.set(frame.agentId, now);

        const prevUrl = urlMapRef.current.get(frame.agentId);
        if (prevUrl) URL.revokeObjectURL(prevUrl);

        const url = URL.createObjectURL(frame.blob);
        urlMapRef.current.set(frame.agentId, url);

        setScreenshots((prev) => {
          const next = new Map(prev);
          next.set(frame.agentId, { url, timestamp: frame.timestamp });
          return next;
        });
      };

      ws.onclose = () => {
        if (!alive) return;
        swarmaFe('useScreenshots', 'close_reconnect_in_2s', { jobId, framesSeen: frameCount });
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        swarmaFe('useScreenshots', 'error', { jobId });
        ws.close();
      };
    }

    connect();

    return () => {
      alive = false;
      swarmaFe('useScreenshots', 'cleanup', { jobId });
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
      lastUiApplyRef.current.clear();
      cleanup();
      setConnected(false);
    };
  }, [jobId, cleanup]);

  return { screenshots, connected };
}
