'use client';

import { useMutation } from '@tanstack/react-query';
import { apiClient, type ApiError } from '@/lib/api-client';
import type { RunScanResponse, ScanConfig } from '@/generated/api-client';

export interface UploadScanParams {
  repoName: string;
  files: File[];
  config?: Partial<ScanConfig>;
}

/**
 * Mutation hook that fires POST /api/scans/upload.
 * Accepts an array of File objects from a folder picker (webkitdirectory)
 * or a single .zip file — works from any OS regardless of hosting environment.
 */
export function useUploadScan() {
  return useMutation<RunScanResponse, ApiError, UploadScanParams>({
    mutationFn: ({ repoName, files, config }) =>
      apiClient.scans.upload(repoName, files, config),
    retry: false,
  });
}
