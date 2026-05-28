'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { Scan } from '@/generated/api-client';

export function useScan(id: string) {
  return useQuery<Scan, ApiError>({
    queryKey: ['scan', id],
    queryFn: () => apiClient.scans.getScan(id),
    enabled: !!id,
    staleTime: 30_000,
    retry: 1,
  });
}
