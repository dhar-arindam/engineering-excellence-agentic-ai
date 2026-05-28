import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';

/**
 * Fetches the unified diff text for a scan's suggested fix.
 * Only enabled when the scan has patch_available === true.
 */
export function usePatch(scanId: string, enabled = true) {
  return useQuery<string, ApiError>({
    queryKey: ['patch', scanId],
    queryFn: () => apiClient.scans.getPatch(scanId),
    enabled: enabled && !!scanId,
    staleTime: Infinity,
    retry: false,
  });
}
