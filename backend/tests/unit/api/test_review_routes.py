"""Unit tests for POST/GET review API routes (no DB, no LLM)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.domain.entities import AgentFinding, EngineeringReviewAggregate, ReviewSummary
from app.domain.enums import AgentName, ReviewStatus, RiskLevel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REVIEW_ID = uuid.uuid4()


def _make_aggregate(review_id: uuid.UUID = REVIEW_ID) -> EngineeringReviewAggregate:
    return EngineeringReviewAggregate(
        review_id=review_id,
        repo_url="https://github.com/test/repo",
        overall_score=78,
        risk_level=RiskLevel.MEDIUM,
        status=ReviewStatus.COMPLETED,
        agent_results=[
            AgentFinding(
                agent_name=AgentName.SENIOR_QA,
                score=80,
                summary="Good coverage.",
                issues=[],
                recommendations=["Increase coverage to 90%."],
            ),
        ],
        created_at=datetime.now(UTC),
    )


def _make_summary(review_id: uuid.UUID = REVIEW_ID) -> ReviewSummary:
    return ReviewSummary(
        review_id=review_id,
        overall_score=78,
        risk_level=RiskLevel.MEDIUM,
        status=ReviewStatus.COMPLETED,
        agent_scores={"SeniorQAAgent": 80},
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def client():
    """Test client with all dependencies overridden."""
    from app.main import create_app
    from app.api.deps import get_orchestrator, get_repository

    aggregate = _make_aggregate()
    summary   = _make_summary()

    mock_orchestrator = AsyncMock()
    mock_orchestrator.orchestrate.return_value = aggregate

    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = aggregate
    mock_repo.get_summary.return_value = summary

    application = create_app()
    application.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    application.dependency_overrides[get_repository]   = lambda: mock_repo

    yield TestClient(application, raise_server_exceptions=True)

    application.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/review
# ---------------------------------------------------------------------------

class TestCreateReview:
    def test_returns_202(self, client):
        resp = client.post("/api/review", json={"repo_url": "https://github.com/owner/repo"})
        assert resp.status_code == 202

    def test_returns_review_id(self, client):
        resp = client.post("/api/review", json={"repo_url": "https://github.com/owner/repo"})
        body = resp.json()
        assert "review_id" in body
        uuid.UUID(body["review_id"])  # must be a valid UUID

    def test_returns_status(self, client):
        resp = client.post("/api/review", json={"repo_url": "https://github.com/owner/repo"})
        assert resp.json()["status"] == "completed"

    def test_local_path_accepted(self, client):
        resp = client.post("/api/review", json={"local_path": "/srv/repos/myapp"})
        assert resp.status_code == 202

    def test_missing_source_returns_422(self, client):
        resp = client.post("/api/review", json={})
        assert resp.status_code == 422

    def test_both_sources_returns_422(self, client):
        resp = client.post(
            "/api/review",
            json={"repo_url": "https://github.com/x/y", "local_path": "/srv/x"},
        )
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/api/review", json=None)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/review/{review_id}
# ---------------------------------------------------------------------------

class TestGetReview:
    def test_returns_200(self, client):
        resp = client.get(f"/api/review/{REVIEW_ID}")
        assert resp.status_code == 200

    def test_response_has_data_key(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}").json()
        assert "data" in body

    def test_overall_score_present(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}").json()
        assert body["data"]["overall_score"] == 78

    def test_agent_results_present(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}").json()
        assert len(body["data"]["agent_results"]) == 1

    def test_invalid_uuid_returns_422(self, client):
        resp = client.get("/api/review/not-a-uuid")
        assert resp.status_code == 422

    def test_not_found_returns_404(self, client):
        from app.core.exceptions import NotFoundError
        # Rebuild client with a repo that raises NotFoundError
        from app.main import create_app
        from app.api.deps import get_repository

        mock_repo = AsyncMock()
        mock_repo.get_by_id.side_effect = NotFoundError("EngineeringReview", str(uuid.uuid4()))

        app = create_app()
        app.dependency_overrides[get_repository] = lambda: mock_repo
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"/api/review/{uuid.uuid4()}")
        assert resp.status_code == 404
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/review/{review_id}/summary
# ---------------------------------------------------------------------------

class TestGetReviewSummary:
    def test_returns_200(self, client):
        resp = client.get(f"/api/review/{REVIEW_ID}/summary")
        assert resp.status_code == 200

    def test_response_has_data_key(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}/summary").json()
        assert "data" in body

    def test_agent_scores_present(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}/summary").json()
        assert "agent_scores" in body["data"]

    def test_no_agent_issues_in_summary(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}/summary").json()
        # Summary must NOT contain full issue lists
        assert "agent_results" not in body["data"]

    def test_overall_score_present(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}/summary").json()
        assert body["data"]["overall_score"] == 78

    def test_risk_level_present(self, client):
        body = client.get(f"/api/review/{REVIEW_ID}/summary").json()
        assert body["data"]["risk_level"] == "Medium"

    def test_not_found_returns_404(self, client):
        from app.core.exceptions import NotFoundError
        from app.main import create_app
        from app.api.deps import get_repository

        mock_repo = AsyncMock()
        mock_repo.get_summary.side_effect = NotFoundError("EngineeringReview", str(uuid.uuid4()))

        app = create_app()
        app.dependency_overrides[get_repository] = lambda: mock_repo
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"/api/review/{uuid.uuid4()}/summary")
        assert resp.status_code == 404
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OpenAPI schema
# ---------------------------------------------------------------------------

class TestOpenAPI:
    def test_docs_accessible(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_schema_has_review_paths(self, client):
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        assert "/api/review" in paths
        assert "/api/review/{review_id}" in paths
        assert "/api/review/{review_id}/summary" in paths

    def test_post_review_has_operation_id(self, client):
        schema = client.get("/openapi.json").json()
        op = schema["paths"]["/api/review"]["post"]
        assert op["operationId"] == "create_review"

    def test_get_review_has_operation_id(self, client):
        schema = client.get("/openapi.json").json()
        op = schema["paths"]["/api/review/{review_id}"]["get"]
        assert op["operationId"] == "get_review"

    def test_get_summary_has_operation_id(self, client):
        schema = client.get("/openapi.json").json()
        op = schema["paths"]["/api/review/{review_id}/summary"]["get"]
        assert op["operationId"] == "get_review_summary"

    def test_health_endpoint_exists(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
