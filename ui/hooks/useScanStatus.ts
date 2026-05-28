'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import type { ScanStatusResponse } from '@/generated/api-client';

/**
 * Polls GET /api/scans/{scanId}/status every 3 s.
 * Polling stops automatically when status is 'completed' or 'failed'.
 */
export function useScanStatus(scanId: string | null) {
  return useQuery<ScanStatusResponse, Error>({
    queryKey: ['scan-status', scanId],
    queryFn: () => apiClient.scans.getStatus(scanId!),
    enabled: !!scanId,
    refetchInterval(query) {
      const status = (query.state.data as ScanStatusResponse | undefined)?.status;
      if (status === 'completed' || status === 'failed') return false;
      return 3_000;
    },
    retry: false,
    staleTime: 0,
  });
}
