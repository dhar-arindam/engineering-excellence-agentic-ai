import type {
  Repository,
  RepositoryListItem,
  RepositoryListResponse,
  CreateRepositoryRequest,
  UpdateRepositoryRequest,
  Scan,
  ScanSummary,
  ScanListParams,
  ScanListResponse,
  PatchAnnotations,
  CreatePRResponse,
  LocalUser,
  RunScanRequest,
  RunScanResponse,
  ScanStatusResponse,
  BranchesResponse,
  PullRequestItem,
  PullRequestsResponse,
  AgentsPerformanceResponse,
  SecurityOverviewResponse,
  RepositoryTrends,
} from '@/generated/api-client';

// ─── Runtime environment ──────────────────────────────────────────────────────

declare global {
  interface Window {
    __ENV?: { NEXT_PUBLIC_API_URL?: string };
  }
}

function resolveApiBase(): string {
  const runtime =
    typeof window !== 'undefined' ? window.__ENV?.NEXT_PUBLIC_API_URL : undefined;
  return (runtime ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');
}

const HTTP_BASE = resolveApiBase();

/** WebSocket base URL — swap http(s) for ws(s) */
export const WS_BASE = HTTP_BASE.replace(/^http/, 'ws');

// ─── Auth token resolution ────────────────────────────────────────────────────

async function resolveAuthToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  try {
    const { createAuthStrategy } = await import('@/lib/auth/authFactory');
    return createAuthStrategy().getAccessToken();
  } catch {
    return null;
  }
}

// ─── Typed API error ──────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(
      typeof body === 'object' && body !== null
        ? (
            ('detail' in body && typeof (body as { detail: unknown }).detail === 'string'
              ? String((body as { detail: unknown }).detail)
              : null) ??
            ('message' in body
              ? String((body as { message: unknown }).message)
              : null) ??
            `Request failed with status ${status}`
          )
        : `Request failed with status ${status}`,
    );
    this.name = 'ApiError';
  }
}

// ─── Core fetch helpers ───────────────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await resolveAuthToken();

  const res = await fetch(`${HTTP_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, body);
  }

  // 204 No Content or empty body — return undefined (typed as T, e.g. void)
  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return undefined as unknown as T;
  }

  return res.json() as Promise<T>;
}

async function requestFormData<T>(path: string, formData: FormData): Promise<T> {
  const token = await resolveAuthToken();

  const res = await fetch(`${HTTP_BASE}${path}`, {
    method: 'POST',
    // Do NOT set Content-Type — browser sets it with the multipart boundary
    headers: {
      ...(token && { Authorization: `Bearer ${token}` }),
    },
    body: formData,
  });

  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, body);
  }

  return res.json() as Promise<T>;
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const token = await resolveAuthToken();

  const res = await fetch(`${HTTP_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'text/plain',
      ...(token && { Authorization: `Bearer ${token}` }),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, body);
  }

  return res.text();
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== '');
  if (!entries.length) return '';
  return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&');
}

// ─── Namespaced API client ────────────────────────────────────────────────────

export const apiClient = {
  // ── Repositories ──────────────────────────────────────────────────────────
  repositories: {
    list(): Promise<RepositoryListResponse> {
      return request<RepositoryListResponse>('/api/repositories');
    },

    get(id: string): Promise<Repository> {
      return request<Repository>(`/api/repositories/${id}`);
    },

    create(data: CreateRepositoryRequest): Promise<Repository> {
      return request<Repository>('/api/repositories', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },

    update(id: string, data: UpdateRepositoryRequest): Promise<Repository> {
      return request<Repository>(`/api/repositories/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      });
    },

    delete(id: string): Promise<void> {
      return request<void>(`/api/repositories/${id}`, { method: 'DELETE' });
    },

    getScans(id: string): Promise<ScanSummary[]> {
      return request<ScanSummary[]>(`/api/repositories/${id}/scans`);
    },

    getTrends(id: string, params?: { branch?: string; days?: number }): Promise<RepositoryTrends> {
      const q = buildQuery(params as Record<string, string | number | boolean | undefined>);
      return request<RepositoryTrends>(`/api/repositories/${id}/trends${q}`);
    },
  },

  // ── Scans ──────────────────────────────────────────────────────────────────
  scans: {
    list(params?: ScanListParams): Promise<ScanListResponse> {
      const q = buildQuery(params as Record<string, string | number | boolean | undefined>);
      return request<ScanListResponse>(`/api/scans${q}`);
    },

    getScan(id: string): Promise<Scan> {
      return request<Scan>(`/api/scans/${id}`);
    },

    run(params: RunScanRequest): Promise<RunScanResponse> {
      return request<RunScanResponse>('/api/scans/run', {
        method: 'POST',
        body: JSON.stringify(params),
      });
    },

    upload(repoName: string, files: File[], config?: object): Promise<RunScanResponse> {
      const formData = new FormData();
      formData.append('repo_name', repoName);
      if (config) formData.append('config', JSON.stringify(config));
      for (const file of files) {
        // webkitRelativePath contains the full relative path (e.g. "my-project/src/app.py")
        const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
        formData.append('files', file, relativePath);
      }
      return requestFormData<RunScanResponse>('/api/scans/upload', formData);
    },

    getStatus(scanId: string): Promise<ScanStatusResponse> {
      return request<ScanStatusResponse>(`/api/scans/${scanId}/status`);
    },

    cancel(scanId: string): Promise<void> {
      return request<void>(`/api/scans/${scanId}/cancel`, { method: 'POST' });
    },

    getPatch(scanId: string): Promise<string> {
      return requestText(`/api/scans/${scanId}/patch`);
    },

    getAnnotations(scanId: string): Promise<PatchAnnotations> {
      return request<PatchAnnotations>(`/api/scans/${scanId}/patch-annotations`);
    },

    createPr(scanId: string): Promise<CreatePRResponse> {
      return request<CreatePRResponse>(`/api/scans/${scanId}/create-pr`, {
        method: 'POST',
      });
    },
  },

  // ── Auth ───────────────────────────────────────────────────────────────────
  auth: {
    getLocalUser(): Promise<LocalUser> {
      return request<LocalUser>('/api/auth/local-user');
    },
  },

  // ── Agents performance ─────────────────────────────────────────────────────
  agents: {
    getPerformance(): Promise<AgentsPerformanceResponse> {
      return request<AgentsPerformanceResponse>('/api/agents/performance');
    },
  },

  // ── Security overview ──────────────────────────────────────────────────────
  security: {
    getOverview(): Promise<SecurityOverviewResponse> {
      return request<SecurityOverviewResponse>('/api/security/overview');
    },
  },

  // ── Repos (branch + PR utility) ───────────────────────────────────────────
  repos: {
    getBranches(repositoryUrl: string): Promise<BranchesResponse> {
      return request<BranchesResponse>(
        `/api/repos/branches?repository_url=${encodeURIComponent(repositoryUrl)}`,
      );
    },

    getPullRequests(repositoryUrl: string, state = 'open'): Promise<PullRequestsResponse> {
      return request<PullRequestsResponse>(
        `/api/repos/pulls?repository_url=${encodeURIComponent(repositoryUrl)}&state=${encodeURIComponent(state)}`,
      );
    },
  },
} as const;

// ─── Legacy flat exports (used by existing hooks — kept for backward compat) ──
// These will be removed once all hooks are updated.

export function runScan(params: RunScanRequest): Promise<RunScanResponse> {
  return apiClient.scans.run(params);
}

export function getScanStatus(scanId: string): Promise<ScanStatusResponse> {
  return apiClient.scans.getStatus(scanId);
}

export function getRepoBranches(repositoryUrl: string): Promise<BranchesResponse> {
  return apiClient.repos.getBranches(repositoryUrl);
}

export function getPatch(scanId: string): Promise<string> {
  return apiClient.scans.getPatch(scanId);
}

export function createPR(scanId: string): Promise<CreatePRResponse> {
  return apiClient.scans.createPr(scanId);
}

export function getPatchAnnotations(scanId: string): Promise<PatchAnnotations> {
  return apiClient.scans.getAnnotations(scanId);
}
