import { useQuery } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { PatchAnnotations } from '@/generated/api-client';

/**
 * Fetches structured patch annotations for a scan.
 * Returns per-file risk scores, hunk-level reasons, references, and
 * estimated impact for each modification.
 *
 * Falls back gracefully — the UI renders without annotations when the
 * endpoint is unavailable (e.g., for analyze-only scans or older records).
 */
export function usePatchAnnotations(scanId: string, enabled = true) {
  return useQuery<PatchAnnotations, ApiError>({
    queryKey: ['patchAnnotations', scanId],
    queryFn: () => apiClient.scans.getAnnotations(scanId),
    enabled: enabled && !!scanId,
    staleTime: Infinity,
    retry: false,
  });
}
