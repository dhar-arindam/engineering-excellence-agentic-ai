'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { ScanListParams, ScanListResponse } from '@/generated/api-client';

export function useScans(params?: ScanListParams) {
  return useQuery<ScanListResponse, ApiError>({
    queryKey: ['scans', params],
    queryFn: () => apiClient.scans.list(params),
    staleTime: 30_000,
  });
}
