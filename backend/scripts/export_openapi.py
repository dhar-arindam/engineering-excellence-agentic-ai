#!/usr/bin/env python3
"""Export versioned OpenAPI JSON specs to the frontend generated directory.

Usage
-----
Run from the repository root::

    python backend/scripts/export_openapi.py

Or via the Makefile target::

    make export-openapi

The script spins up the FastAPI app in-process (no running server required),
fetches ``/openapi/v1.json`` and ``/openapi/v2.json`` using a TestClient, and
writes the results to ``ui/src/generated/``.

After running this script, generate TypeScript types::

    cd ui
    npx openapi-typescript src/generated/openapi-v2.json --output src/generated/api-types.ts

Generate a full typed API client::

    npx openapi-typescript-codegen \\
        --input  src/generated/openapi-v2.json \\
        --output src/generated/api-client \\
        --client fetch
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate repository root and wire Python path
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent          # backend/scripts/
_BACKEND_DIR = _SCRIPT_DIR.parent                       # backend/
_REPO_ROOT = _BACKEND_DIR.parent                        # repo root
_OUTPUT_DIR = _REPO_ROOT / "ui" / "src" / "generated"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("🔧  Importing FastAPI app…")

    # Patch Redis pool so the lifespan doesn't try to connect.
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.infrastructure.redis_client.create_redis_pool",
        return_value=AsyncMock(),
    ):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)

        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        for version in ("v1", "v2"):
            url = f"/openapi/{version}.json"
            print(f"📥  Fetching {url}…")
            response = client.get(url)
            if response.status_code != 200:
                print(f"❌  Failed to fetch {url}: HTTP {response.status_code}", file=sys.stderr)
                sys.exit(1)

            out_path = _OUTPUT_DIR / f"openapi-{version}.json"
            schema = response.json()
            out_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            endpoint_count = len(schema.get("paths", {}))
            print(f"✅  Wrote {out_path.relative_to(_REPO_ROOT)}  ({endpoint_count} paths)")

    print()
    print("🎉  OpenAPI export complete.")
    print()
    print("Next steps — generate TypeScript types:")
    print()
    print("  cd ui")
    print("  npx openapi-typescript src/generated/openapi-v2.json \\")
    print("    --output src/generated/api-types.ts")
    print()
    print("Generate a full typed API client:")
    print()
    print("  npx openapi-typescript-codegen \\")
    print("    --input  src/generated/openapi-v2.json \\")
    print("    --output src/generated/api-client \\")
    print("    --client fetch")


if __name__ == "__main__":
    main()
