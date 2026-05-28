import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { CreatePRResponse } from '@/generated/api-client';

/**
 * Mutation hook that fires POST /api/scans/{scanId}/create-pr.
 * Invalidates the scan detail query on success so the PR status refreshes.
 */
export function useCreatePR(scanId: string) {
  const queryClient = useQueryClient();

  return useMutation<CreatePRResponse, ApiError, void>({
    mutationKey: ['createPR', scanId],
    mutationFn: () => apiClient.scans.createPr(scanId),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['createPR', scanId] });
    },
  });
}
