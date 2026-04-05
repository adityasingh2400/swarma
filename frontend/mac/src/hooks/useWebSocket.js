import { useState, useEffect, useRef, useCallback } from 'react';
import { swarmaFe } from '../utils/debugLog';

export function useWebSocket(jobId) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState([]);
  const [lastEvent, setLastEvent] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const subscribersRef = useRef(new Set());

  const subscribe = useCallback((fn) => {
    subscribersRef.current.add(fn);
    return () => subscribersRef.current.delete(fn);
  }, []);

  const dispatch = useCallback((event) => {
    subscribersRef.current.forEach((fn) => fn(event));
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let alive = true;

    function connect() {
      if (!alive) return;

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host || 'localhost:8080';
      const url = `${protocol}//${host}/ws/${jobId}/events`;
      swarmaFe('useWebSocket', 'connect_attempt', { jobId, url });

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!alive) return;
        swarmaFe('useWebSocket', 'open', { jobId });
        setConnected(true);
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      ws.onmessage = (msg) => {
        if (!alive) return;
        try {
          const event = JSON.parse(msg.data);
          swarmaFe('useWebSocket', 'message_raw', {
            jobId,
            jsonChars: typeof msg.data === 'string' ? msg.data.length : 0,
            type: event?.type,
          });
          setEvents((prev) => prev.length >= 200 ? [...prev.slice(-100), event] : [...prev, event]);
          setLastEvent(event);
          dispatch(event);
        } catch (e) {
          swarmaFe('useWebSocket', 'message_parse_error', { jobId, err: String(e) });
        }
      };

      ws.onclose = () => {
        if (!alive) return;
        swarmaFe('useWebSocket', 'close_reconnect_in_2s', { jobId });
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        swarmaFe('useWebSocket', 'error', { jobId });
        ws.close();
      };
    }

    connect();

    return () => {
      alive = false;
      swarmaFe('useWebSocket', 'cleanup_close', { jobId });
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
      setConnected(false);
      setEvents([]);
      setLastEvent(null);
    };
  }, [jobId, dispatch]);

  const send = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
  }, []);

  return { connected, events, lastEvent, subscribe, send };
}
