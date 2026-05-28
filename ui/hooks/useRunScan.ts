'use client';

import { useMutation } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { RunScanRequest, RunScanResponse } from '@/generated/api-client';

/**
 * Mutation hook that fires POST /api/scans/run.
 * Retries are intentionally disabled — a failed scan should not auto-retry.
 */
export function useRunScan() {
  return useMutation<RunScanResponse, ApiError, RunScanRequest>({
    mutationFn: (params: RunScanRequest) => apiClient.scans.run(params),
    retry: false,
  });
}
