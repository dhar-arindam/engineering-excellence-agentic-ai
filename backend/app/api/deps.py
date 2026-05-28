"""FastAPI dependency injection wiring."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agents import (
    SecurityExpertAgent,
    SeniorArchitectAgent,
    SeniorDeveloperAgent,
    SeniorQAAgent,
    SeniorSREAgent,
)
from app.application.orchestrator import EngineeringReviewOrchestrator
from app.application.scoring_engine import ScoringEngine
from app.core.config import settings
from app.infrastructure.db.repository import EngineeringReviewRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.github.client import GitHubClient
from app.infrastructure.intelligence.cicd_intelligence import RealCiCdIntelligenceService
from app.infrastructure.intelligence.code_intelligence import RealCodeIntelligenceService
from app.infrastructure.intelligence.security_intelligence import RealSecurityIntelligenceService
from app.infrastructure.intelligence.test_intelligence import RealTestIntelligenceService
from app.infrastructure.llm.openai_adapter import OpenAIAdapter
from app.infrastructure.repository_ingestion.github_loader import GitHubRepositoryLoader
from app.infrastructure.repository_ingestion.local_loader import LocalRepositoryLoader
from app.infrastructure.tools.stubs import StubArchitectureAnalysisService


@lru_cache
def get_scoring_engine() -> ScoringEngine:
    return ScoringEngine()


@lru_cache
def get_local_loader() -> LocalRepositoryLoader:
    return LocalRepositoryLoader()


@lru_cache
def get_github_loader() -> GitHubRepositoryLoader:
    return GitHubRepositoryLoader()


@lru_cache
def get_llm_adapter() -> OpenAIAdapter:
    return OpenAIAdapter()


@lru_cache
def get_code_intelligence_service() -> RealCodeIntelligenceService:
    return RealCodeIntelligenceService()


@lru_cache
def get_test_intelligence_service() -> RealTestIntelligenceService:
    return RealTestIntelligenceService()


@lru_cache
def get_cicd_intelligence_service() -> RealCiCdIntelligenceService:
    return RealCiCdIntelligenceService()


@lru_cache
def get_security_intelligence_service() -> RealSecurityIntelligenceService:
    return RealSecurityIntelligenceService()


def get_tool_services() -> dict:  # type: ignore[type-arg]
    return {
        "code": get_code_intelligence_service(),
        "test": get_test_intelligence_service(),
        "cicd": get_cicd_intelligence_service(),
        "security": get_security_intelligence_service(),
        "architecture": StubArchitectureAnalysisService(),
    }


def get_agents() -> list:  # type: ignore[type-arg]
    llm = get_llm_adapter()
    return [
        SeniorQAAgent(),
        SeniorDeveloperAgent(llm_adapter=llm),
        SeniorArchitectAgent(),
        SeniorSREAgent(),
        SecurityExpertAgent(),
    ]


async def get_repository(
    session: AsyncSession = Depends(get_db_session),
) -> EngineeringReviewRepository:
    return EngineeringReviewRepository(session)


async def get_orchestrator(
    repository: EngineeringReviewRepository = Depends(get_repository),
) -> EngineeringReviewOrchestrator:
    tools = get_tool_services()
    return EngineeringReviewOrchestrator(
        agents=get_agents(),
        scoring_engine=get_scoring_engine(),
        repository=repository,
        local_loader=get_local_loader(),
        github_loader=get_github_loader(),
        code_service=tools["code"],
        test_service=tools["test"],
        cicd_service=tools["cicd"],
        security_service=tools["security"],
        architecture_service=tools["architecture"],
    )


@lru_cache
def get_github_client() -> GitHubClient:
    """Return a singleton GitHubClient using the configured token."""
    return GitHubClient(token=settings.github_token)


async def get_orchestrator_for_webhook() -> EngineeringReviewOrchestrator:
    """Build an orchestrator outside of a FastAPI Depends context.

    Used by the webhook background task which runs after the request
    lifecycle has ended (no active Depends chain available).
    """
    from app.infrastructure.db.session import AsyncSessionFactory  # lazy import

    session = AsyncSessionFactory()
    repository = EngineeringReviewRepository(session)
    tools = get_tool_services()
    return EngineeringReviewOrchestrator(
        agents=get_agents(),
        scoring_engine=get_scoring_engine(),
        repository=repository,
        local_loader=get_local_loader(),
        github_loader=get_github_loader(),
        code_service=tools["code"],
        test_service=tools["test"],
        cicd_service=tools["cicd"],
        security_service=tools["security"],
        architecture_service=tools["architecture"],
    )
