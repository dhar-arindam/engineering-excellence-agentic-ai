'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import type { BranchesResponse } from '@/generated/api-client';
import { useDebounce } from './useDebounce';

/** Matches https://github.com/owner/repo with an optional trailing slash */
const GITHUB_REPO_RE = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/;

function isValidGithubRepo(url: string): boolean {
  return GITHUB_REPO_RE.test(url.trim());
}

/**
 * Fetches branches for a GitHub repository URL.
 *
 * - Only fires when the URL passes the GitHub repo regex
 * - Debounces the URL by 600 ms to avoid spamming the API while typing
 * - Caches results for 5 minutes (branch lists rarely change mid-session)
 */
export function useRepoBranches(repositoryUrl: string) {
  const debouncedUrl = useDebounce(repositoryUrl.trim(), 600);
  const enabled = isValidGithubRepo(debouncedUrl);

  return useQuery<BranchesResponse, Error>({
    queryKey: ['repo-branches', debouncedUrl],
    queryFn: () => apiClient.repos.getBranches(debouncedUrl),
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}
