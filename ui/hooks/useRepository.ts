'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { Repository } from '@/generated/api-client';

export function useRepository(id: string) {
  return useQuery<Repository, ApiError>({
    queryKey: ['repository', id],
    queryFn: () => apiClient.repositories.get(id),
    enabled: !!id,
    staleTime: 60_000,
  });
}
