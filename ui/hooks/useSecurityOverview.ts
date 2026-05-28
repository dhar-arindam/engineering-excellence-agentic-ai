'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { SecurityOverviewResponse } from '@/generated/api-client';

export function useSecurityOverview() {
  return useQuery<SecurityOverviewResponse, ApiError>({
    queryKey: ['security', 'overview'],
    queryFn: () => apiClient.security.getOverview(),
    staleTime: 60_000,
  });
}
