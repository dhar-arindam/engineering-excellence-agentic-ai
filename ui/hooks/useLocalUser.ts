'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { LocalUser } from '@/generated/api-client';

export function useLocalUser() {
  return useQuery<LocalUser, ApiError>({
    queryKey: ['local-user'],
    queryFn: () => apiClient.auth.getLocalUser(),
    staleTime: Infinity,
    retry: false,
  });
}
