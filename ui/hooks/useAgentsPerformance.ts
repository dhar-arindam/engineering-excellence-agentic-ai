'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { AgentsPerformanceResponse } from '@/generated/api-client';

export function useAgentsPerformance() {
  return useQuery<AgentsPerformanceResponse, ApiError>({
    queryKey: ['agents', 'performance'],
    queryFn: () => apiClient.agents.getPerformance(),
    staleTime: 60_000,
  });
}
