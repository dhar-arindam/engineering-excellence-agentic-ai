"""Regex-based security scanning engine.

Provides:
- scan_file_sync()       — scan one file for secrets + insecure patterns
- scan_repo_sync()       — scan all relevant files in a repository
- detect_dependency_files()  — identify dependency manifests
- detect_security_infra()    — detect scanner configs + security policy files

No LLM calls. No external scanners. No side effects beyond reading files.
All heavy work is sync (designed to run in asyncio executor).

IMPORTANT: This scanner uses pattern matching and is intentionally conservative
(prefers false positives over false negatives). It NEVER logs or stores the
actual matched secret values — only redacted previews.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from app.infrastructure.intelligence.security_models import (
    InsecurePatternFinding,
    SecretFinding,
    SecurityMetrics,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Max bytes to read per file (avoid reading huge binaries)
_MAX_FILE_BYTES = 500_000  # 500 KB

# Extensions that may contain secrets or insecure patterns
_SCANNABLE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".php",
    ".cs", ".cpp", ".c", ".swift", ".kt", ".rs",
    ".env", ".cfg", ".ini", ".conf", ".config",
    ".yml", ".yaml", ".toml",
    ".sh", ".bash", ".zsh", ".ps1",
    ".json",       # package.json, appsettings.json, etc.
    ".properties", # Java properties files
    ".xml",        # Maven, Spring, etc.
    "",            # Extensionless files: Dockerfile, Jenkinsfile, Makefile
})

# Extensions / names to always skip
_SKIP_EXTENSIONS = frozenset({".lock", ".sum", ".ico", ".png", ".jpg", ".jpeg",
                               ".gif", ".svg", ".woff", ".ttf", ".eot", ".pdf",
                               ".zip", ".tar", ".gz", ".bin", ".exe", ".pyc"})
_SKIP_NAMES = frozenset({"package-lock.json", "yarn.lock", "poetry.lock",
                          "Pipfile.lock", "pnpm-lock.yaml", "composer.lock"})

# Directories to skip
_SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".tox",
})

# Files that are docs/tests where HTTP URLs are expected (lower signal)
_LOW_SIGNAL_PATTERNS = re.compile(
    r"(test_|_test\.|spec\.|\.spec\.|\.md$|\.rst$|\.txt$|fixture|mock|stub)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------
# Each entry: (pattern_type, compiled_regex, value_group_index)
# The value group (if present) captures the secret value for redaction.

_SECRET_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    # Generic key/secret assignment: VAR = "value" or VAR = 'value'
    ("api_key",
     re.compile(r'(?i)\b(?:api[_-]?key|apikey)\s*[=:]\s*["\']([A-Za-z0-9_\-]{8,})["\']'),
     1),
    ("secret_key",
     re.compile(r'(?i)\b(?:secret[_-]?key|secretkey|secret)\s*[=:]\s*["\']([^"\']{4,})["\']'),
     1),
    ("password",
     re.compile(r'(?i)\b(?:password|passwd|pwd)\s*[=:]\s*["\']([^"\']{4,})["\']'),
     1),
    ("token",
     re.compile(r'(?i)\b(?:token|auth[_-]?token|access[_-]?token|bearer[_-]?token)\s*[=:]\s*["\']([A-Za-z0-9_\-\.]{8,})["\']'),
     1),
    # Private key headers (PEM format)
    ("private_key",
     re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'),
     0),
    # Connection strings with embedded credentials
    ("connection_string",
     re.compile(r'(?i)(?:postgres(?:ql)?|mysql|mongodb|redis|amqp|mssql)://[^:@\s]+:[^@\s]+@'),
     0),
    # AWS-style access key IDs (20-char uppercase alphanumeric starting with AKIA)
    ("api_key",
     re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
     0),
    # Generic high-entropy assignments (long values after = that look like tokens)
    ("token",
     re.compile(r'(?i)\b(?:authorization|auth)\s*[=:]\s*["\'](?:bearer\s+)?([A-Za-z0-9_\-\.]{32,})["\']'),
     1),
]


# ---------------------------------------------------------------------------
# Insecure pattern detection
# ---------------------------------------------------------------------------

_INSECURE_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Plain HTTP URLs (skip localhost/127.0.0.1/internal)
    ("http_url",
     re.compile(r'http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|::1|example\.com)[a-zA-Z0-9]')),
    # Weak hash algorithms
    ("weak_hash",
     re.compile(r'(?i)\b(?:md5|sha1)\s*\(')),
    # eval() usage in Python/JS
    ("eval_usage",
     re.compile(r'\beval\s*\(')),
    # Shell injection risks: subprocess with shell=True
    ("shell_injection",
     re.compile(r'(?i)subprocess\.[a-z_]+\s*\([^)]*shell\s*=\s*True')),
    # Django / Flask DEBUG = True in non-test context
    ("debug_enabled",
     re.compile(r'(?i)\bDEBUG\s*[=:]\s*True\b')),
    # Pickle deserialization (can execute arbitrary code)
    ("insecure_deserialization",
     re.compile(r'\bpickle\.loads?\s*\(')),
    # Hard-coded SSL verification disable
    ("ssl_disabled",
     re.compile(r'(?i)verify\s*=\s*False')),
]


# ---------------------------------------------------------------------------
# Dependency file detection
# ---------------------------------------------------------------------------

# (filename_pattern, display_name)
_DEPENDENCY_FILES: list[re.Pattern] = [
    re.compile(r"^requirements.*\.txt$", re.IGNORECASE),
    re.compile(r"^package\.json$"),
    re.compile(r"^Pipfile$"),
    re.compile(r"^pyproject\.toml$"),
    re.compile(r"^pom\.xml$"),
    re.compile(r"^build\.gradle(\.kts)?$"),
    re.compile(r"^go\.mod$"),
    re.compile(r"^Cargo\.toml$"),
    re.compile(r"^composer\.json$"),
    re.compile(r"^Gemfile$"),
    re.compile(r"^setup\.py$"),
    re.compile(r"^setup\.cfg$"),
]

_SECURITY_SCANNER_FILES = frozenset({
    ".github/dependabot.yml", ".github/dependabot.yaml",
    ".snyk", "snyk.json",
    ".safety-policy.yml",
    "bandit.yml", ".bandit",
    "trivy.yaml", "trivy.yml",
})

_SECURITY_POLICY_FILES = frozenset({
    "SECURITY.md", "security.md",
    ".github/SECURITY.md",
    "SECURITY.txt",
})


# ---------------------------------------------------------------------------
# File scanning (sync)
# ---------------------------------------------------------------------------

def _should_scan(rel_path: str) -> bool:
    """Return True if the file should be scanned for security issues."""
    p = Path(rel_path)

    # Skip locked/generated files
    if p.name in _SKIP_NAMES:
        return False
    if p.suffix.lower() in _SKIP_EXTENSIONS:
        return False

    # Skip directories (shouldn't happen in a flat file list, but guard anyway)
    parts = set(p.parts[:-1])
    if parts & _SKIP_DIRS:
        return False

    ext = p.suffix.lower()
    return ext in _SCANNABLE_EXTENSIONS


def _redact(value: str) -> str:
    """Produce a safe redacted preview of a secret value."""
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def scan_file_sync(
    abs_path: str,
    rel_path: str,
) -> tuple[list[SecretFinding], list[InsecurePatternFinding], Optional[str]]:
    """
    Scan a single file for secrets and insecure patterns.

    Returns:
        (secret_findings, insecure_findings, error_message_or_None)
    """
    secret_findings: list[SecretFinding] = []
    insecure_findings: list[InsecurePatternFinding] = []

    try:
        raw = Path(abs_path).read_bytes()
    except OSError as exc:
        return [], [], f"Cannot read {rel_path}: {exc}"

    # Quick binary check — skip files with null bytes
    if b"\x00" in raw[:1024]:
        return [], [], None

    try:
        text = raw[:_MAX_FILE_BYTES].decode("utf-8", errors="replace")
    except Exception:
        return [], [], f"Decode error: {rel_path}"

    is_low_signal = bool(_LOW_SIGNAL_PATTERNS.search(rel_path))
    lines = text.splitlines()

    for line_no, line in enumerate(lines, start=1):
        # Secret scan
        for pattern_type, regex, value_group in _SECRET_PATTERNS:
            match = regex.search(line)
            if match:
                if value_group > 0 and match.lastindex and match.lastindex >= value_group:
                    raw_value = match.group(value_group)
                else:
                    raw_value = match.group(0)

                secret_findings.append(SecretFinding(
                    file_path=rel_path,
                    line_number=line_no,
                    pattern_type=pattern_type,
                    redacted_preview=_redact(raw_value),
                ))

        # Insecure pattern scan (skip low-signal files for HTTP check only)
        for pattern_type, regex in _INSECURE_PATTERNS:
            if is_low_signal and pattern_type == "http_url":
                continue
            match = regex.search(line)
            if match:
                # Safe snippet: truncate to 120 chars, no secret values
                snippet = line.strip()[:120]
                insecure_findings.append(InsecurePatternFinding(
                    file_path=rel_path,
                    line_number=line_no,
                    pattern_type=pattern_type,
                    snippet=snippet,
                ))

    return secret_findings, insecure_findings, None


# ---------------------------------------------------------------------------
# Repository-level scan (sync, runs in executor)
# ---------------------------------------------------------------------------

def scan_repo_sync(
    root: str,
    file_tree: list[str],
) -> tuple[list[SecretFinding], list[InsecurePatternFinding], list[str]]:
    """
    Scan all relevant files in the repository.

    Args:
        root:      Absolute path to repository root.
        file_tree: Full list of relative file paths.

    Returns:
        (secret_findings, insecure_findings, scan_errors)
    """
    import os

    all_secrets: list[SecretFinding] = []
    all_insecure: list[InsecurePatternFinding] = []
    errors: list[str] = []

    for rel in file_tree:
        if not _should_scan(rel):
            continue
        abs_path = os.path.join(root, rel)
        secrets, insecure, error = scan_file_sync(abs_path, rel)
        all_secrets.extend(secrets)
        all_insecure.extend(insecure)
        if error:
            errors.append(error)

    return all_secrets, all_insecure, errors


# ---------------------------------------------------------------------------
# Dependency and infra detection
# ---------------------------------------------------------------------------

def detect_dependency_files(file_tree: list[str]) -> list[str]:
    """Return file paths that are dependency manifests."""
    results: list[str] = []
    for path in file_tree:
        name = Path(path).name
        if any(pat.match(name) for pat in _DEPENDENCY_FILES):
            results.append(path)
    return results


def detect_security_infra(file_tree: list[str]) -> tuple[bool, bool]:
    """
    Return (has_dependency_scanner, has_security_policy).

    Checks for Dependabot/Snyk/Trivy config files and SECURITY.md.
    """
    normalized = {p.replace("\\", "/").lower() for p in file_tree}
    scanner_files_lower = {f.lower() for f in _SECURITY_SCANNER_FILES}
    policy_files_lower = {f.lower() for f in _SECURITY_POLICY_FILES}

    has_scanner = bool(normalized & scanner_files_lower)
    has_policy = bool(normalized & policy_files_lower)
    return has_scanner, has_policy


# ---------------------------------------------------------------------------
# Metrics builder
# ---------------------------------------------------------------------------

def build_security_metrics(
    all_secrets: list[SecretFinding],
    all_insecure: list[InsecurePatternFinding],
    file_tree: list[str],
    scanned_files: int,
) -> SecurityMetrics:
    """Aggregate scan results into a ``SecurityMetrics`` model."""
    dep_files = detect_dependency_files(file_tree)
    has_scanner, has_policy = detect_security_infra(file_tree)

    # Build the flat string lists required by the spec
    potential_secrets = [
        f"{f.file_path}:{f.line_number}:{f.pattern_type}"
        for f in all_secrets
    ]
    insecure_list = [
        f"{f.file_path}:{f.line_number}:{f.pattern_type}"
        for f in all_insecure
    ]
    password_instances = [
        f"{f.file_path}:{f.line_number}"
        for f in all_secrets
        if f.pattern_type == "password"
    ]

    # uses_https: True when no HTTP findings exist
    http_findings = [f for f in all_insecure if f.pattern_type == "http_url"]
    uses_https = len(http_findings) == 0

    has_requirements = any(
        Path(f).name.lower().startswith("requirements") and f.endswith(".txt")
        for f in file_tree
    )

    return SecurityMetrics(
        potential_secrets_found=potential_secrets,
        insecure_patterns=insecure_list,
        dependency_files=dep_files,
        uses_https=uses_https,
        has_requirements_txt=has_requirements,
        hardcoded_password_instances=password_instances,
        secret_count=len(all_secrets),
        insecure_pattern_count=len(all_insecure),
        has_dependency_scanner=has_scanner,
        has_security_policy=has_policy,
        scanned_files=scanned_files,
    )
