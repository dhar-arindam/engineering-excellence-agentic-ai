'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { RepositoryTrends } from '@/generated/api-client';

interface UseTrendsParams {
  branch?: string;
  days?: number;
}

export function useRepositoryTrends(repoId: string, params?: UseTrendsParams) {
  return useQuery<RepositoryTrends, ApiError>({
    queryKey: ['repository-trends', repoId, params],
    queryFn: () => apiClient.repositories.getTrends(repoId, params),
    enabled: !!repoId,
    staleTime: 2 * 60_000, // 2 minutes
  });
}
