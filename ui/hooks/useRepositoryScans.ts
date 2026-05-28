'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { ScanSummary } from '@/generated/api-client';

export function useRepositoryScans(repositoryId: string) {
  return useQuery<ScanSummary[], ApiError>({
    queryKey: ['repository-scans', repositoryId],
    queryFn: () => apiClient.repositories.getScans(repositoryId),
    enabled: !!repositoryId,
    staleTime: 30_000,
  });
}
