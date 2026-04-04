import { useState, useEffect, useRef, useCallback } from 'react';
import {
  SCREENSHOT_FRAME_VERSION,
  SCREENSHOT_HEADER_BYTES,
} from '../contracts.js';

function parseFrame(arrayBuffer) {
  if (!arrayBuffer || arrayBuffer.byteLength < SCREENSHOT_HEADER_BYTES) return null;
  const view = new DataView(arrayBuffer);
  if (view.getUint8(0) !== SCREENSHOT_FRAME_VERSION) return null;
  const idSlice = new Uint8Array(arrayBuffer, 1, 32);
  const agentId = new TextDecoder('utf-8', { fatal: false })
    .decode(idSlice)
    .replace(/\0/g, '')
    .trim();
  const timestamp = view.getUint32(33, false);
  const jpeg = new Uint8Array(arrayBuffer, SCREENSHOT_HEADER_BYTES);
  if (jpeg.length === 0) return null;
  const blob = new Blob([jpeg], { type: 'image/jpeg' });
  return { agentId, timestamp, blob };
}

export function useScreenshots(jobId) {
  const [connected, setConnected] = useState(false);
  const [version, setVersion] = useState(0);
  const urlsRef = useRef(new Map());
  const metaRef = useRef(new Map());
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const bump = useCallback(() => setVersion((v) => v + 1), []);

  const revokeAgent = useCallback((agentId) => {
    const prev = urlsRef.current.get(agentId);
    if (prev) URL.revokeObjectURL(prev);
    urlsRef.current.delete(agentId);
    metaRef.current.delete(agentId);
  }, []);

  const clearAll = useCallback(() => {
    for (const id of urlsRef.current.keys()) {
      revokeAgent(id);
    }
  }, [revokeAgent]);

  useEffect(() => {
    if (!jobId) {
      clearAll();
      bump();
      return;
    }

    let alive = true;

    function connect() {
      if (!alive) return;
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host || 'localhost:8080';
      const url = `${protocol}//${host}/ws/${jobId}/screenshots`;
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        if (!alive) return;
        setConnected(true);
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      ws.onmessage = (ev) => {
        if (!alive) return;
        const buf = ev.data;
        if (!(buf instanceof ArrayBuffer)) return;
        const parsed = parseFrame(buf);
        if (!parsed) return;
        const { agentId, timestamp, blob } = parsed;
        revokeAgent(agentId);
        const objectUrl = URL.createObjectURL(blob);
        urlsRef.current.set(agentId, objectUrl);
        metaRef.current.set(agentId, { timestamp, updatedAt: Date.now() });
        bump();
      };

      ws.onclose = () => {
        if (!alive) return;
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      alive = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
      setConnected(false);
      clearAll();
      bump();
    };
  }, [jobId, bump, clearAll, revokeAgent]);

  const getScreenshotUrl = useCallback(
    (agentId) => {
      void version;
      if (!agentId) return null;
      return urlsRef.current.get(agentId) || null;
    },
    [version],
  );

  const getScreenshotMeta = useCallback(
    (agentId) => {
      void version;
      if (!agentId) return null;
      return metaRef.current.get(agentId) || null;
    },
    [version],
  );

  return {
    connected,
    getScreenshotUrl,
    getScreenshotMeta,
    revokeAgent,
    clearAll,
  };
}
