# TypeScript Code Generation Guide

This document explains how to generate fully-typed TypeScript types and an API
client from the backend's OpenAPI schemas.

---

## Prerequisites

Install the code-generation tools once in the `ui/` directory:

```bash
cd ui
npm install -D openapi-typescript openapi-typescript-codegen
```

---

## Step 1 — Export OpenAPI JSON

From the repository root:

```bash
make export-openapi
```

This runs `backend/scripts/export_openapi.py` and writes:

```
ui/src/generated/openapi-v1.json   ← v1 (frozen)
ui/src/generated/openapi-v2.json   ← v2 (active)
```

---

## Step 2 — Generate TypeScript types

```bash
make gen-types
# or manually:
cd ui
npx openapi-typescript src/generated/openapi-v2.json \
  --output src/generated/api-types.ts
```

This produces a single `api-types.ts` file with all request/response types
derived from the OpenAPI schema.  Import them anywhere in the Next.js app:

```typescript
import type { components } from "@/generated/api-types";

type ScanRunResponse  = components["schemas"]["ScanRunResponse"];
type ScanDetailResponse = components["schemas"]["ScanDetailResponse"];
type ErrorResponse    = components["schemas"]["ErrorResponse"];
```

---

## Step 3 — Generate a typed API client

```bash
make gen-client
# or manually:
cd ui
npx openapi-typescript-codegen \
  --input  src/generated/openapi-v2.json \
  --output src/generated/api-client \
  --client fetch \
  --useOptions \
  --useUnionTypes
```

Output structure:

```
ui/src/generated/api-client/
  core/
    ApiError.ts
    BaseHttpRequest.ts
    FetchHttpRequest.ts
    OpenAPI.ts
    request.ts
  models/
    ScanRunRequest.ts
    ScanRunResponse.ts
    ScanDetailResponse.ts
    ErrorResponse.ts
    ...
  services/
    ScansService.ts
    ReviewsService.ts
    GithubService.ts
    HealthService.ts
  index.ts
```

---

## Step 4 — Initialise the API client

Create (or update) `ui/lib/api-client.ts`:

```typescript
import { OpenAPI } from "@/generated/api-client/core/OpenAPI";
import { ScansService } from "@/generated/api-client/services/ScansService";
import { ReviewsService } from "@/generated/api-client/services/ReviewsService";

// Configure base URL once — reads the runtime-injected env variable.
OpenAPI.BASE =
  (typeof window !== "undefined" && (window as any).__ENV?.NEXT_PUBLIC_API_URL) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

// Re-export typed services for use throughout the app.
export { ScansService, ReviewsService };
```

---

## Step 5 — Use with TanStack Query

```typescript
import { useQuery, useMutation } from "@tanstack/react-query";
import { ScansService } from "@/lib/api-client";

// Poll scan status
export function useScanStatus(scanId: string) {
  return useQuery({
    queryKey: ["scan", scanId, "status"],
    queryFn: () => ScansService.v2GetScanStatus({ scanId }),
    refetchInterval: (data) =>
      data?.status === "completed" || data?.status === "failed" ? false : 2000,
  });
}

// Get full scan detail (v2 only)
export function useScanDetail(scanId: string) {
  return useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => ScansService.v2GetScan({ scanId }),
  });
}

// Trigger a new scan
export function useRunScan() {
  return useMutation({
    mutationFn: ScansService.v2RunScan,
  });
}
```

---

## Versioning notes

| Version | Endpoint prefix | Swagger UI      | Schema URL            |
|---------|-----------------|-----------------|-----------------------|
| v1      | `/api/v1/...`   | `/docs/v1`      | `/openapi/v1.json`    |
| v2      | `/api/v2/...`   | `/docs` (default) | `/openapi/v2.json`  |

- **v1 is frozen** — no new fields, no breaking changes.
- **v2 is active** — new features land here first.
- The legacy un-prefixed routes (`/api/scans`, `/api/review`, etc.) remain
  available for backward compatibility with pre-versioning clients.

---

## Keeping types up to date

Re-run after any backend schema change:

```bash
make gen-types    # re-exports schema + regenerates types
make gen-client   # re-exports schema + regenerates client
```

Add both to your CI pipeline to catch type drift early:

```yaml
# .github/workflows/ci.yml
- name: Export OpenAPI + check types compile
  run: |
    make export-openapi
    make gen-types
    cd ui && npx tsc --noEmit
```
