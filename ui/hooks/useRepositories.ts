'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { RepositoryListResponse } from '@/generated/api-client';

export function useRepositories() {
  return useQuery<RepositoryListResponse, ApiError>({
    queryKey: ['repositories'],
    queryFn: () => apiClient.repositories.list(),
    staleTime: 60_000,
  });
}
