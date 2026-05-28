"""Tests for POST /api/github/webhook route.

Uses FastAPI TestClient with dependency_overrides — no real GitHub API,
no real DB, no real LLM.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(action: str = "opened") -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": 7,
            "title": "feat: caching",
            "body": None,
            "base": {
                "sha": "aaa",
                "ref": "main",
                "repo": {"clone_url": "https://github.com/org/my-repo.git"},
            },
            "head": {"sha": "bbb", "ref": "feature/x"},
            "user": {"login": "dev"},
        },
        "repository": {
            "name": "my-repo",
            "full_name": "org/my-repo",
            "owner": {"login": "org"},
            "clone_url": "https://github.com/org/my-repo.git",
            "html_url": "https://github.com/org/my-repo",
        },
    }


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Fixture: test client with mocked processor
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Return a TestClient with GitHubClient and orchestrator mocked out."""
    app = create_app()

    mock_github_client = MagicMock()
    mock_github_client.get_pr_diff = AsyncMock()
    mock_github_client.post_comment = AsyncMock(return_value={"id": 1})

    mock_orchestrator = MagicMock()

    with (
        patch("app.api.routes.github.get_github_client", return_value=mock_github_client),
        patch("app.api.routes.github.get_orchestrator_for_webhook", new=AsyncMock(return_value=mock_orchestrator)),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            c.mock_github_client = mock_github_client
            c.mock_orchestrator = mock_orchestrator
            yield c


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


class TestSignatureVerification:
    def test_no_secret_configured_skips_verification(self, client):
        """When github_webhook_secret is empty, any payload is accepted."""
        with patch("app.api.routes.github.settings") as mock_settings:
            mock_settings.github_webhook_secret = ""
            body = json.dumps(_make_payload("closed")).encode()
            resp = client.post(
                "/api/github/webhook",
                content=body,
                headers={"X-GitHub-Event": "pull_request",
                         "Content-Type": "application/json"},
            )
        assert resp.status_code in (200, 202)

    def test_valid_signature_accepted(self, client):
        with patch("app.api.routes.github.settings") as mock_settings:
            mock_settings.github_webhook_secret = "mysecret"
            body = json.dumps(_make_payload("closed")).encode()
            sig = _sign(body, "mysecret")
            resp = client.post(
                "/api/github/webhook",
                content=body,
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": sig,
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code in (200, 202)

    def test_invalid_signature_rejected(self, client):
        with patch("app.api.routes.github.settings") as mock_settings:
            mock_settings.github_webhook_secret = "mysecret"
            body = json.dumps(_make_payload()).encode()
            resp = client.post(
                "/api/github/webhook",
                content=body,
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=badhash",
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code == 401

    def test_missing_signature_when_secret_set(self, client):
        with patch("app.api.routes.github.settings") as mock_settings:
            mock_settings.github_webhook_secret = "mysecret"
            body = json.dumps(_make_payload()).encode()
            resp = client.post(
                "/api/github/webhook",
                content=body,
                headers={"X-GitHub-Event": "pull_request",
                         "Content-Type": "application/json"},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------


class TestEventFiltering:
    def _post(self, client, payload: dict, event: str) -> object:
        with patch("app.api.routes.github.settings") as s:
            s.github_webhook_secret = ""
            body = json.dumps(payload).encode()
            return client.post(
                "/api/github/webhook",
                content=body,
                headers={"X-GitHub-Event": event,
                         "Content-Type": "application/json"},
            )

    def test_non_pr_event_ignored(self, client):
        resp = self._post(client, {"action": "created"}, "push")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "ignored"

    def test_pr_closed_action_ignored(self, client):
        resp = self._post(client, _make_payload("closed"), "pull_request")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "ignored"

    def test_pr_opened_queued(self, client):
        resp = self._post(client, _make_payload("opened"), "pull_request")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"

    def test_pr_synchronize_queued(self, client):
        resp = self._post(client, _make_payload("synchronize"), "pull_request")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"

    def test_pr_reopened_queued(self, client):
        resp = self._post(client, _make_payload("reopened"), "pull_request")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"

    def test_invalid_json_returns_400(self, client):
        with patch("app.api.routes.github.settings") as s:
            s.github_webhook_secret = ""
            resp = client.post(
                "/api/github/webhook",
                content=b"not-json",
                headers={"X-GitHub-Event": "pull_request",
                         "Content-Type": "application/json"},
            )
        assert resp.status_code == 400

    def test_response_includes_pr_number(self, client):
        resp = self._post(client, _make_payload("opened"), "pull_request")
        data = resp.json()
        assert data["pr_number"] == 7

    def test_response_includes_action(self, client):
        resp = self._post(client, _make_payload("synchronize"), "pull_request")
        data = resp.json()
        assert data["action"] == "synchronize"
