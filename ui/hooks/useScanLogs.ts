'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { WS_BASE } from '@/lib/api-client';
import type { ScanLogEntry } from '@/types/scan';

interface UseScanLogsResult {
  logs: ScanLogEntry[];
  connected: boolean;
  clearLogs: () => void;
}

/**
 * Opens a WebSocket to WS /api/scans/{scanId}/logs and streams
 * ScanLogEntry messages into `logs`.
 *
 * Auto-reconnects every 2 s on unexpected close.
 * Stops connecting when `active` is false.
 */
export function useScanLogs(scanId: string | null, active: boolean): UseScanLogsResult {
  const [logs, setLogs] = useState<ScanLogEntry[]>([]);
  const [connected, setConnected] = useState(false);

  // Use a ref so the closure inside the effect always sees the latest value
  // without triggering re-runs of the effect.
  const activeRef = useRef(active);
  useEffect(() => { activeRef.current = active; }, [active]);

  useEffect(() => {
    if (!scanId || !active) return;

    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (disposed) return;

      const ws = new WebSocket(`${WS_BASE}/api/scans/${scanId}/logs`);

      ws.onopen = () => {
        if (!disposed) setConnected(true);
      };

      ws.onmessage = ({ data }) => {
        if (disposed) return;
        try {
          const entry = JSON.parse(data as string) as ScanLogEntry;
          setLogs(prev => [...prev, entry]);
        } catch {
          // Silently skip unparseable messages
        }
      };

      ws.onerror = () => {
        if (!disposed) setConnected(false);
      };

      ws.onclose = () => {
        if (disposed) return;
        setConnected(false);
        // Reconnect only while the scan is still active
        if (activeRef.current) {
          retryTimer = setTimeout(connect, 2_000);
        }
      };

      return ws;
    }

    const ws = connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      ws?.close();
      setConnected(false);
    };
  }, [scanId, active]); // eslint-disable-line react-hooks/exhaustive-deps

  const clearLogs = useCallback(() => setLogs([]), []);

  return { logs, connected, clearLogs };
}
