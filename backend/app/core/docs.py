"""Custom Swagger UI and ReDoc HTML generators.

Produces a fully themed Swagger UI (dark mode, platform logo, request-duration
display, persistent auth) and an enhanced ReDoc page — without requiring
any extra Python or npm dependencies.

CDN assets use the same ``cdn.jsdelivr.net`` origin as FastAPI's built-in
Swagger, so no static-file server is needed.

Usage::

    from app.core.docs import get_swagger_html, get_redoc_html

    @app.get("/docs", include_in_schema=False)
    async def swagger_endpoint():
        return get_swagger_html(openapi_url="/openapi.json", title=app.title)

    @app.get("/redoc", include_in_schema=False)
    async def redoc_endpoint():
        return get_redoc_html(openapi_url="/openapi.json", title=app.title)
"""
from __future__ import annotations

import base64

from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# CDN asset URLs
# ---------------------------------------------------------------------------

_SWAGGER_VERSION = "5.18.2"
_REDOC_VERSION = "2.1.5"

_SWAGGER_JS_URL = (
    f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_VERSION}"
    "/swagger-ui-bundle.js"
)
_SWAGGER_CSS_URL = (
    f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_VERSION}"
    "/swagger-ui.css"
)
_REDOC_JS_URL = (
    f"https://cdn.jsdelivr.net/npm/redoc@{_REDOC_VERSION}"
    "/bundles/redoc.standalone.js"
)

# ---------------------------------------------------------------------------
# Platform logo — inline SVG (no external image request)
# Stylised "EI" monogram on a blue-to-purple gradient with circuit motif.
# ---------------------------------------------------------------------------

_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"'
    ' width="48" height="48">'
    "<defs>"
    '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0%" stop-color="#1f6feb"/>'
    '<stop offset="100%" stop-color="#8b5cf6"/>'
    "</linearGradient>"
    "</defs>"
    '<rect width="48" height="48" rx="10" fill="url(#g)"/>'
    '<text x="7" y="30" font-family="monospace,sans-serif" font-size="14"'
    ' font-weight="700" fill="#ffffff" letter-spacing="1">EI</text>'
    '<circle cx="37" cy="13" r="5" fill="none" stroke="#58a6ff" stroke-width="1.5"/>'
    '<line x1="37" y1="8"  x2="37" y2="4"  stroke="#58a6ff" stroke-width="1.5"/>'
    '<line x1="37" y1="18" x2="37" y2="22" stroke="#58a6ff" stroke-width="1.5"/>'
    '<line x1="32" y1="13" x2="28" y2="13" stroke="#58a6ff" stroke-width="1.5"/>'
    '<line x1="42" y1="13" x2="46" y2="13" stroke="#58a6ff" stroke-width="1.5"/>'
    "</svg>"
)

LOGO_DATA_URI: str = (
    "data:image/svg+xml;base64," + base64.b64encode(_LOGO_SVG.encode()).decode()
)

# ---------------------------------------------------------------------------
# Dark theme CSS
# GitHub-inspired dark palette (bg=#0d1117) applied over Swagger UI v5.
# ---------------------------------------------------------------------------

_DARK_CSS = """
/* ── Reset / Base ───────────────────────────────────────────────────── */
html, body { background-color: #0d1117; color: #c9d1d9; }
.swagger-ui { background: #0d1117; color: #c9d1d9; }

/* ── Topbar ─────────────────────────────────────────────────────────── */
.swagger-ui .topbar {
  background: #161b22;
  border-bottom: 1px solid #30363d;
  padding: 8px 20px;
}
/* Replace default Swagger logo with our logo via CSS */
.topbar-wrapper .link svg,
.topbar-wrapper .link img { display: none !important; }
.topbar-wrapper .link::before {
  content: "";
  display: inline-block;
  width: 32px; height: 32px;
  background: url("__LOGO__") center/contain no-repeat;
  vertical-align: middle;
  margin-right: 10px;
}
.topbar-wrapper .link span {
  display: inline-block;
  color: #e6edf3;
  font-size: 15px;
  font-weight: 700;
  vertical-align: middle;
  letter-spacing: 0.3px;
}

/* ── Info block ─────────────────────────────────────────────────────── */
.swagger-ui .information-container,
.swagger-ui .information-container .info { background: transparent; }
.swagger-ui .info .title  { color: #e6edf3; }
.swagger-ui .info .title small.version-stamp { background: #1f6feb; color: #fff; }
.swagger-ui .info a { color: #58a6ff; }
.swagger-ui .info p,
.swagger-ui .info li  { color: #8b949e; }
.swagger-ui .info code { background: #1c2128; color: #ff7b72; padding: 2px 5px; border-radius: 4px; }
.swagger-ui .info h1, .swagger-ui .info h2,
.swagger-ui .info h3   { color: #c9d1d9; }

/* ── Scheme / server selector ───────────────────────────────────────── */
.swagger-ui .scheme-container {
  background: #161b22;
  border: 1px solid #30363d;
  box-shadow: none;
  padding: 12px 20px;
}
.swagger-ui .servers > label { color: #8b949e; }
.swagger-ui .servers > label select {
  background: #0d1117; color: #c9d1d9;
  border: 1px solid #30363d; border-radius: 6px;
}

/* ── Operation blocks ───────────────────────────────────────────────── */
.swagger-ui .opblock-tag {
  color: #e6edf3;
  border-bottom: 1px solid #21262d;
  font-size: 1.1rem;
}
.swagger-ui .opblock-tag:hover { background: #161b22; }
.swagger-ui .opblock {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  margin-bottom: 6px;
  box-shadow: none;
}
.swagger-ui .opblock .opblock-summary {
  border-bottom: 1px solid #21262d;
}
.swagger-ui .opblock .opblock-summary-path,
.swagger-ui .opblock .opblock-summary-path__deprecated { color: #c9d1d9; }
.swagger-ui .opblock .opblock-summary-description { color: #8b949e; }
.swagger-ui .opblock .opblock-body { background: #0d1117; }
.swagger-ui .opblock-section-header { background: #1c2128; }
.swagger-ui .opblock-section-header h4 { color: #c9d1d9; }
.swagger-ui .opblock-description-wrapper p,
.swagger-ui .opblock-external-docs-wrapper p { color: #8b949e; }

/* HTTP method colours — keep vivid for readability */
.swagger-ui .opblock.opblock-post   { border-color: #238636; background: rgba(35,134,54,0.08); }
.swagger-ui .opblock.opblock-get    { border-color: #1f6feb; background: rgba(31,111,235,0.08); }
.swagger-ui .opblock.opblock-delete { border-color: #da3633; background: rgba(218,54,51,0.08); }
.swagger-ui .opblock.opblock-put    { border-color: #9e6a03; background: rgba(158,106,3,0.08); }
.swagger-ui .opblock.opblock-patch  { border-color: #388bfd; background: rgba(56,139,253,0.08); }

/* ── Parameters / request body ──────────────────────────────────────── */
.swagger-ui table thead tr td,
.swagger-ui table thead tr th { color: #8b949e; border-bottom: 1px solid #21262d; }
.swagger-ui table tbody tr td  { border-bottom: 1px solid #161b22; color: #c9d1d9; }
.swagger-ui .parameter__name   { color: #c9d1d9; }
.swagger-ui .parameter__type   { color: #79c0ff; }
.swagger-ui .parameter__deprecated { color: #8b949e; text-decoration: line-through; }
.swagger-ui .parameter__in     { color: #56d364; font-size: 0.75em; }

/* ── Input / textarea ───────────────────────────────────────────────── */
.swagger-ui input[type=text],
.swagger-ui input[type=email],
.swagger-ui input[type=password],
.swagger-ui textarea,
.swagger-ui select {
  background: #1c2128;
  color: #c9d1d9;
  border: 1px solid #30363d;
  border-radius: 6px;
}
.swagger-ui input[type=text]:focus,
.swagger-ui textarea:focus { border-color: #58a6ff; outline: none; }

/* ── Buttons ────────────────────────────────────────────────────────── */
.swagger-ui .btn {
  background: transparent;
  border: 1px solid #30363d;
  color: #c9d1d9;
  border-radius: 6px;
}
.swagger-ui .btn:hover { background: #1c2128; }
.swagger-ui .btn.execute {
  background: #1f6feb; border-color: #1f6feb; color: #fff;
}
.swagger-ui .btn.execute:hover { background: #388bfd; }
.swagger-ui .btn.authorize {
  background: #238636; border-color: #238636; color: #fff;
}
.swagger-ui .btn.authorize svg { fill: #fff; }
.swagger-ui .btn.cancel   { border-color: #da3633; color: #f85149; }
.swagger-ui .authorization__btn { color: #58a6ff; }

/* ── Response section ───────────────────────────────────────────────── */
.swagger-ui .responses-inner { background: #0d1117; }
.swagger-ui .response-col_status  { color: #c9d1d9; }
.swagger-ui .response-col_links   { color: #58a6ff; }
.swagger-ui .response .response-col_description__inner p { color: #8b949e; }
.swagger-ui .highlight-code,
.swagger-ui .microlight { background: #1c2128 !important; color: #c9d1d9; }
.swagger-ui .tab li { color: #8b949e; cursor: pointer; }
.swagger-ui .tab li.active { color: #c9d1d9; border-bottom: 2px solid #1f6feb; }

/* ── Models / schemas ───────────────────────────────────────────────── */
.swagger-ui section.models {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
}
.swagger-ui section.models h4 { color: #c9d1d9; }
.swagger-ui .model-box  { background: #1c2128; }
.swagger-ui .model .property.primitive { color: #79c0ff; }
.swagger-ui .model-title { color: #c9d1d9; }
.swagger-ui .model span { color: #c9d1d9; }
.swagger-ui .model-toggle { color: #8b949e; }
.swagger-ui .prop-name  { color: #79c0ff; }
.swagger-ui .prop-type  { color: #56d364; }
.swagger-ui .prop-format { color: #9e6a03; }

/* ── Auth dialog ────────────────────────────────────────────────────── */
.swagger-ui .dialog-ux .modal-ux {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 8px;
  color: #c9d1d9;
}
.swagger-ui .dialog-ux .modal-ux-header { border-bottom: 1px solid #30363d; }
.swagger-ui .dialog-ux .modal-ux-header h3 { color: #e6edf3; }

/* ── Filter bar ─────────────────────────────────────────────────────── */
.swagger-ui .filter .operation-filter-input {
  background: #1c2128; color: #c9d1d9;
  border: 1px solid #30363d; border-radius: 6px;
}

/* ── Markdown inside descriptions ───────────────────────────────────── */
.swagger-ui .markdown h1,
.swagger-ui .markdown h2,
.swagger-ui .markdown h3 { color: #c9d1d9; border-bottom: 1px solid #21262d; }
.swagger-ui .markdown p,
.swagger-ui .markdown li  { color: #8b949e; }
.swagger-ui .markdown code {
  background: #1c2128; color: #ff7b72;
  padding: 2px 5px; border-radius: 3px;
}
.swagger-ui .markdown pre  { background: #1c2128; border: 1px solid #30363d; border-radius: 6px; }
.swagger-ui .markdown a    { color: #58a6ff; }

/* ── Rate-limit / custom headers docs badge ─────────────────────────── */
.x-rate-limit-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  background: rgba(158,106,3,0.2);
  border: 1px solid #9e6a03;
  color: #e3b341;
  margin-left: 6px;
  vertical-align: middle;
}

/* ── Scrollbar (webkit) ─────────────────────────────────────────────── */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #161b22; }
::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #484f58; }
"""

# ---------------------------------------------------------------------------
# Rate-limit header documentation banner
# Injected as visible HTML beneath the Swagger info block via JS.
# ---------------------------------------------------------------------------

_RATE_LIMIT_BANNER_HTML = """
<div id="rate-limit-docs" style="
  background: #1c2128;
  border: 1px solid #30363d;
  border-left: 4px solid #9e6a03;
  border-radius: 6px;
  padding: 12px 16px;
  margin: 12px 0 20px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 0.85rem;
  color: #c9d1d9;
  line-height: 1.6;
">
  <strong style="color:#e3b341;">&#9888; Rate Limiting</strong>
  &nbsp;&nbsp;All API endpoints are subject to rate limiting.
  Every response includes the following headers:
  <table style="margin-top:8px;border-collapse:collapse;width:100%;font-size:0.82rem;">
    <thead>
      <tr style="border-bottom:1px solid #30363d;">
        <th style="text-align:left;padding:4px 8px;color:#8b949e;">Header</th>
        <th style="text-align:left;padding:4px 8px;color:#8b949e;">Type</th>
        <th style="text-align:left;padding:4px 8px;color:#8b949e;">Description</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="padding:4px 8px;font-family:monospace;color:#79c0ff;">X-RateLimit-Limit</td>
        <td style="padding:4px 8px;color:#56d364;">integer</td>
        <td style="padding:4px 8px;">Maximum requests allowed in the current window.</td>
      </tr>
      <tr style="background:rgba(255,255,255,0.02);">
        <td style="padding:4px 8px;font-family:monospace;color:#79c0ff;">X-RateLimit-Remaining</td>
        <td style="padding:4px 8px;color:#56d364;">integer</td>
        <td style="padding:4px 8px;">Requests remaining in the current window.</td>
      </tr>
      <tr>
        <td style="padding:4px 8px;font-family:monospace;color:#79c0ff;">X-RateLimit-Reset</td>
        <td style="padding:4px 8px;color:#56d364;">integer</td>
        <td style="padding:4px 8px;">Unix timestamp (seconds) when the window resets.</td>
      </tr>
      <tr style="background:rgba(255,255,255,0.02);">
        <td style="padding:4px 8px;font-family:monospace;color:#79c0ff;">X-Request-ID</td>
        <td style="padding:4px 8px;color:#56d364;">string&nbsp;(UUID)</td>
        <td style="padding:4px 8px;">
          Unique trace identifier echoed on every response.
          Pass <code style="background:#0d1117;padding:1px 4px;border-radius:3px;">X-Request-ID</code>
          on requests to correlate client and server logs.
        </td>
      </tr>
    </tbody>
  </table>
</div>
"""


def _build_swagger_html(
    *,
    openapi_url: str,
    title: str,
    swagger_js_url: str = _SWAGGER_JS_URL,
    swagger_css_url: str = _SWAGGER_CSS_URL,
    swagger_ui_parameters: dict | None = None,
) -> str:
    """Return a complete dark-themed Swagger UI HTML page as a string."""
    params = {
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "filter": True,
        "tryItOutEnabled": False,
        "requestSnippetsEnabled": True,
        "syntaxHighlight": {"theme": "monokai"},
        "tagsSorter": "alpha",
        "operationsSorter": "alpha",
        "defaultModelsExpandDepth": 1,
        "defaultModelExpandDepth": 2,
    }
    if swagger_ui_parameters:
        params.update(swagger_ui_parameters)

    import json as _json
    params_json = _json.dumps(params)

    # Inject logo data URI into the CSS string
    dark_css = _DARK_CSS.replace("__LOGO__", LOGO_DATA_URI)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title}</title>
  <link rel="icon" type="image/svg+xml"
        href="{LOGO_DATA_URI}"/>
  <link rel="stylesheet" type="text/css" href="{swagger_css_url}"/>
  <style>{dark_css}</style>
</head>
<body>
  <div id="swagger-ui"></div>

  <script src="{swagger_js_url}"></script>
  <script>
    window.addEventListener("load", function () {{
      const ui = SwaggerUIBundle(Object.assign({{
        url: "{openapi_url}",
        dom_id: "#swagger-ui",
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout",
        deepLinking: true,
      }}, {params_json}));
      window.ui = ui;

      // Inject rate-limit header docs banner after the info block loads.
      function injectBanner() {{
        const info = document.querySelector(".swagger-ui .information-container");
        if (info && !document.getElementById("rate-limit-docs")) {{
          info.insertAdjacentHTML("afterend", {_json.dumps(_RATE_LIMIT_BANNER_HTML)});
        }}
      }}
      // Retry a few times to survive Swagger's async render cycle.
      let attempts = 0;
      const timer = setInterval(function () {{
        injectBanner();
        if (document.getElementById("rate-limit-docs") || ++attempts > 20) {{
          clearInterval(timer);
        }}
      }}, 300);
    }});
  </script>
</body>
</html>"""


def _build_redoc_html(
    *,
    openapi_url: str,
    title: str,
    redoc_js_url: str = _REDOC_JS_URL,
) -> str:
    """Return a ReDoc HTML page with x-logo support and dark-friendly settings."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title} — ReDoc</title>
  <link rel="icon" type="image/svg+xml" href="{LOGO_DATA_URI}"/>
  <style>
    body {{ margin: 0; padding: 0; }}
  </style>
</head>
<body>
  <redoc spec-url="{openapi_url}"
         expand-responses="200,202"
         hide-loading
         native-scrollbars
         theme='{{"colors":{{"primary":{{"main":"#1f6feb"}}}},
                   "typography":{{"fontFamily":"-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"}},
                   "sidebar":{{"backgroundColor":"#161b22","textColor":"#c9d1d9"}},
                   "rightPanel":{{"backgroundColor":"#0d1117"}}}}'>
  </redoc>
  <script src="{redoc_js_url}"></script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_swagger_html(
    *,
    openapi_url: str,
    title: str,
    swagger_ui_parameters: dict | None = None,
) -> HTMLResponse:
    """Return a dark-themed Swagger UI :class:`~fastapi.responses.HTMLResponse`."""
    html = _build_swagger_html(
        openapi_url=openapi_url,
        title=title,
        swagger_ui_parameters=swagger_ui_parameters,
    )
    return HTMLResponse(content=html, status_code=200)


def get_redoc_html(*, openapi_url: str, title: str) -> HTMLResponse:
    """Return a ReDoc :class:`~fastapi.responses.HTMLResponse`."""
    html = _build_redoc_html(openapi_url=openapi_url, title=title)
    return HTMLResponse(content=html, status_code=200)
