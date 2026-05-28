'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type {
  RepositoryListItem,
  CreateRepositoryRequest,
  UpdateRepositoryRequest,
} from '@/generated/api-client';

export function useCreateRepository() {
  const queryClient = useQueryClient();
  return useMutation<RepositoryListItem, ApiError, CreateRepositoryRequest>({
    mutationFn: (data) => apiClient.repositories.create(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] });
    },
  });
}

export function useUpdateRepository(id: string) {
  const queryClient = useQueryClient();
  return useMutation<RepositoryListItem, ApiError, UpdateRepositoryRequest>({
    mutationFn: (data) => apiClient.repositories.update(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] });
      void queryClient.invalidateQueries({ queryKey: ['repository', id] });
    },
  });
}

export function useDeleteRepository() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (id) => apiClient.repositories.delete(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] });
    },
  });
}
