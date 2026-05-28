"""Tests for RealSecurityIntelligenceService and security scanning engine."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.infrastructure.intelligence.security_engine import (
    build_security_metrics,
    detect_dependency_files,
    detect_security_infra,
    scan_file_sync,
    scan_repo_sync,
)
from app.infrastructure.intelligence.security_intelligence import RealSecurityIntelligenceService
from app.infrastructure.intelligence.security_models import SecurityAnalysisResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> RealSecurityIntelligenceService:
    return RealSecurityIntelligenceService()


@pytest.fixture()
def clean_repo(tmp_path: Path) -> Path:
    """Repo with no secrets, only HTTPS, requirements.txt present."""
    (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "import os\nAPI_URL = 'https://api.example.com'\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def dirty_repo(tmp_path: Path) -> Path:
    """Repo with secrets, HTTP usage, passwords, and insecure patterns."""
    (tmp_path / "config.py").write_text(
        textwrap.dedent("""\
            API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"
            SECRET_KEY = "super_secret_value_here"
            PASSWORD = "mysecretpassword123"
            DB_URL = "postgresql://admin:password123@localhost/db"
        """),
        encoding="utf-8",
    )
    (tmp_path / "http_client.py").write_text(
        "url = 'http://external-api.example.com/endpoint'\n",
        encoding="utf-8",
    )
    (tmp_path / "utils.py").write_text(
        textwrap.dedent("""\
            import hashlib
            import subprocess
            def check(data):
                return hashlib.md5(data).hexdigest()
            def run(cmd):
                subprocess.run(cmd, shell=True)
        """),
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("requests==2.28.0\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# scan_file_sync — secret detection
# ---------------------------------------------------------------------------


def test_detects_api_key(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text('API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"\n', encoding="utf-8")
    secrets, _, err = scan_file_sync(str(f), "config.py")
    assert err is None
    assert any(s.pattern_type == "api_key" for s in secrets)


def test_detects_secret_key(tmp_path: Path):
    f = tmp_path / "settings.py"
    f.write_text("SECRET_KEY = 'super_secret_value_here'\n", encoding="utf-8")
    secrets, _, _ = scan_file_sync(str(f), "settings.py")
    assert any(s.pattern_type == "secret_key" for s in secrets)


def test_detects_password(tmp_path: Path):
    f = tmp_path / "db.py"
    f.write_text('PASSWORD = "mysecretpassword123"\n', encoding="utf-8")
    secrets, _, _ = scan_file_sync(str(f), "db.py")
    assert any(s.pattern_type == "password" for s in secrets)


def test_detects_connection_string(tmp_path: Path):
    f = tmp_path / "db.py"
    f.write_text('DB_URL = "postgresql://admin:password123@localhost/mydb"\n', encoding="utf-8")
    secrets, _, _ = scan_file_sync(str(f), "db.py")
    assert any(s.pattern_type == "connection_string" for s in secrets)


def test_detects_private_key(tmp_path: Path):
    f = tmp_path / "key.pem"
    f.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQ\n", encoding="utf-8")
    secrets, _, _ = scan_file_sync(str(f), "key.pem")
    assert any(s.pattern_type == "private_key" for s in secrets)


def test_redacted_preview_hides_secret(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text('API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"\n', encoding="utf-8")
    secrets, _, _ = scan_file_sync(str(f), "config.py")
    assert secrets
    # The actual key must not appear in the redacted preview
    for s in secrets:
        assert "abcdefghijklmnopqrstuvwxyz" not in s.redacted_preview
        assert "***" in s.redacted_preview


def test_no_secrets_in_clean_file(tmp_path: Path):
    f = tmp_path / "app.py"
    f.write_text("import os\nAPI_URL = 'https://api.example.com'\n", encoding="utf-8")
    secrets, _, _ = scan_file_sync(str(f), "app.py")
    assert secrets == []


def test_skips_binary_files(tmp_path: Path):
    f = tmp_path / "image.png"
    f.write_bytes(b"\x00\x01\x02API_KEY='secret'\xff\xfe")
    secrets, insecure, err = scan_file_sync(str(f), "image.png")
    assert secrets == []
    assert insecure == []
    assert err is None


def test_missing_file_returns_error(tmp_path: Path):
    _, _, err = scan_file_sync(str(tmp_path / "nonexistent.py"), "nonexistent.py")
    assert err is not None


def test_line_number_is_correct(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text("x = 1\ny = 2\nPASSWORD = 'secret123'\n", encoding="utf-8")
    secrets, _, _ = scan_file_sync(str(f), "config.py")
    pwd = [s for s in secrets if s.pattern_type == "password"]
    assert pwd
    assert pwd[0].line_number == 3


# ---------------------------------------------------------------------------
# scan_file_sync — insecure pattern detection
# ---------------------------------------------------------------------------


def test_detects_http_url(tmp_path: Path):
    f = tmp_path / "client.py"
    f.write_text("url = 'http://external-api.example.com/v1'\n", encoding="utf-8")
    _, insecure, _ = scan_file_sync(str(f), "client.py")
    assert any(i.pattern_type == "http_url" for i in insecure)


def test_ignores_localhost_http(tmp_path: Path):
    f = tmp_path / "client.py"
    f.write_text("url = 'http://localhost:8000/api'\n", encoding="utf-8")
    _, insecure, _ = scan_file_sync(str(f), "client.py")
    assert not any(i.pattern_type == "http_url" for i in insecure)


def test_detects_md5(tmp_path: Path):
    f = tmp_path / "utils.py"
    f.write_text("import hashlib\nhashlib.md5(data)\n", encoding="utf-8")
    _, insecure, _ = scan_file_sync(str(f), "utils.py")
    assert any(i.pattern_type == "weak_hash" for i in insecure)


def test_detects_shell_true(tmp_path: Path):
    f = tmp_path / "runner.py"
    f.write_text("import subprocess\nsubprocess.run(cmd, shell=True)\n", encoding="utf-8")
    _, insecure, _ = scan_file_sync(str(f), "runner.py")
    assert any(i.pattern_type == "shell_injection" for i in insecure)


def test_detects_eval(tmp_path: Path):
    f = tmp_path / "app.py"
    f.write_text("result = eval(user_input)\n", encoding="utf-8")
    _, insecure, _ = scan_file_sync(str(f), "app.py")
    assert any(i.pattern_type == "eval_usage" for i in insecure)


def test_http_skipped_in_test_file(tmp_path: Path):
    """HTTP URLs in test files are low signal and should be ignored."""
    f = tmp_path / "test_client.py"
    f.write_text("url = 'http://external.example.com/api'\n", encoding="utf-8")
    _, insecure, _ = scan_file_sync(str(f), "test_client.py")
    assert not any(i.pattern_type == "http_url" for i in insecure)


def test_ssl_verify_false(tmp_path: Path):
    f = tmp_path / "client.py"
    f.write_text("requests.get(url, verify=False)\n", encoding="utf-8")
    _, insecure, _ = scan_file_sync(str(f), "client.py")
    assert any(i.pattern_type == "ssl_disabled" for i in insecure)


# ---------------------------------------------------------------------------
# detect_dependency_files
# ---------------------------------------------------------------------------


def test_detect_requirements_txt():
    files = ["requirements.txt", "requirements-dev.txt", "app/main.py"]
    result = detect_dependency_files(files)
    assert "requirements.txt" in result
    assert "requirements-dev.txt" in result
    assert "app/main.py" not in result


def test_detect_package_json():
    files = ["package.json", "src/index.js"]
    result = detect_dependency_files(files)
    assert "package.json" in result


def test_detect_pyproject_toml():
    files = ["pyproject.toml", "README.md"]
    result = detect_dependency_files(files)
    assert "pyproject.toml" in result


def test_detect_multiple_dep_files():
    files = ["requirements.txt", "package.json", "go.mod", "Cargo.toml"]
    result = detect_dependency_files(files)
    assert len(result) == 4


# ---------------------------------------------------------------------------
# detect_security_infra
# ---------------------------------------------------------------------------


def test_detects_dependabot():
    files = [".github/dependabot.yml", "app/main.py"]
    has_scanner, _ = detect_security_infra(files)
    assert has_scanner is True


def test_detects_security_md():
    files = ["SECURITY.md", "README.md"]
    _, has_policy = detect_security_infra(files)
    assert has_policy is True


def test_no_security_infra():
    files = ["app/main.py", "requirements.txt"]
    has_scanner, has_policy = detect_security_infra(files)
    assert has_scanner is False
    assert has_policy is False


# ---------------------------------------------------------------------------
# scan_repo_sync
# ---------------------------------------------------------------------------


def test_scan_repo_finds_secrets(dirty_repo: Path):
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    secrets, _, errors = scan_repo_sync(str(dirty_repo), files)
    assert len(secrets) > 0
    assert errors == []


def test_scan_repo_finds_insecure(dirty_repo: Path):
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    _, insecure, _ = scan_repo_sync(str(dirty_repo), files)
    assert any(i.pattern_type == "http_url" for i in insecure)
    assert any(i.pattern_type == "weak_hash" for i in insecure)
    assert any(i.pattern_type == "shell_injection" for i in insecure)


def test_scan_repo_clean(clean_repo: Path):
    files = [str(p.relative_to(clean_repo)) for p in clean_repo.rglob("*") if p.is_file()]
    secrets, insecure, errors = scan_repo_sync(str(clean_repo), files)
    assert secrets == []
    assert not any(i.pattern_type == "http_url" for i in insecure)


def test_scan_repo_skips_lock_files(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        '{"dependencies": {"evil": {"version": "1.0"}}}\n', encoding="utf-8"
    )
    files = ["package-lock.json"]
    secrets, _, _ = scan_repo_sync(str(tmp_path), files)
    assert secrets == []


# ---------------------------------------------------------------------------
# RealSecurityIntelligenceService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_analyze_returns_dict(dirty_repo: Path, service: RealSecurityIntelligenceService):
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    result = await service.analyze(files, str(dirty_repo))

    assert "hardcoded_secrets_found" in result
    assert result["hardcoded_secrets_found"] is True
    assert result["secret_count"] > 0
    assert result["has_requirements_txt"] is True


@pytest.mark.asyncio()
async def test_analyze_structured_returns_typed(dirty_repo: Path, service: RealSecurityIntelligenceService):
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    result = await service.analyze_structured(files, str(dirty_repo))
    assert isinstance(result, SecurityAnalysisResult)
    assert result.metrics.secret_count > 0


@pytest.mark.asyncio()
async def test_analyze_clean_repo(clean_repo: Path, service: RealSecurityIntelligenceService):
    files = [str(p.relative_to(clean_repo)) for p in clean_repo.rglob("*") if p.is_file()]
    result = await service.analyze(files, str(clean_repo))
    assert result["hardcoded_secrets_found"] is False
    assert result["uses_https"] is True
    assert result["has_requirements_txt"] is True


@pytest.mark.asyncio()
async def test_analyze_no_local_path(service: RealSecurityIntelligenceService):
    result = await service.analyze(["requirements.txt", "app/main.py"], local_path=None)
    assert result["security_metrics"] == {}
    assert result["secret_count"] == 0
    assert result["has_requirements_txt"] is True  # detected from file_tree


@pytest.mark.asyncio()
async def test_analyze_backward_compatible_keys(dirty_repo: Path, service: RealSecurityIntelligenceService):
    """Verify all stub contract keys are present."""
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    result = await service.analyze(files, str(dirty_repo))
    for key in ("hardcoded_secrets_found", "secret_locations",
                "vulnerable_dependencies", "has_dependency_scanner",
                "security_headers_configured"):
        assert key in result, f"Missing backward-compat key: {key}"


@pytest.mark.asyncio()
async def test_analyze_detects_passwords(dirty_repo: Path, service: RealSecurityIntelligenceService):
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    result = await service.analyze(files, str(dirty_repo))
    assert len(result["hardcoded_password_instances"]) > 0


@pytest.mark.asyncio()
async def test_analyze_uses_https_false_on_http(dirty_repo: Path, service: RealSecurityIntelligenceService):
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    result = await service.analyze(files, str(dirty_repo))
    # dirty_repo has http:// in http_client.py
    assert result["uses_https"] is False


@pytest.mark.asyncio()
async def test_analyze_detects_dependabot(tmp_path: Path, service: RealSecurityIntelligenceService):
    dep_dir = tmp_path / ".github"
    dep_dir.mkdir()
    (dep_dir / "dependabot.yml").write_text(
        "version: 2\nupdates:\n  - package-ecosystem: pip\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    files = [".github/dependabot.yml", "app.py"]
    result = await service.analyze(files, str(tmp_path))
    assert result["has_dependency_scanner"] is True


@pytest.mark.asyncio()
async def test_secret_findings_are_redacted(dirty_repo: Path, service: RealSecurityIntelligenceService):
    files = [str(p.relative_to(dirty_repo)) for p in dirty_repo.rglob("*") if p.is_file()]
    result = await service.analyze_structured(files, str(dirty_repo))
    for sf in result.secret_findings:
        # Actual secret values must not appear unredacted
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in sf.redacted_preview
        assert "mysecretpassword123" not in sf.redacted_preview
        assert "***" in sf.redacted_preview
