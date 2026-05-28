"""Tests for app/application/retrieval_tuning.py."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.retrieval_tuning import (
    AgentContextEnricher,
    ArchitectQueryStrategy,
    DevQueryStrategy,
    QAQueryStrategy,
    RetrievalStrategy,
    RetrievalStrategyRegistry,
    SREQueryStrategy,
    SecurityQueryStrategy,
)
from app.domain.enums import AgentName
from app.infrastructure.embeddings.models import CodeChunk, SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(content: str = "def foo(): pass", score: float = 0.9) -> SearchResult:
    chunk = CodeChunk(
        id=uuid.uuid4(),
        file_path="app/core.py",
        start_line=1,
        end_line=5,
        content=content,
        language="python",
    )
    return SearchResult(chunk=chunk, score=score)


def _mock_retrieval_service(results: list[SearchResult] | None = None) -> MagicMock:
    svc = MagicMock()
    svc.search = AsyncMock(return_value=results or [_make_result()])
    return svc


_BASE_CONTEXT: dict[str, Any] = {
    "repo_name": "my-repo",
    "file_paths": ["app/main.py", "app/core.py", "tests/test_core.py"],
    "primary_language": "Python",
    "frameworks": ["FastAPI", "SQLAlchemy"],
    "summary": "Backend API service",
}


# ---------------------------------------------------------------------------
# RetrievalStrategy ABC
# ---------------------------------------------------------------------------


class TestRetrievalStrategyABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            RetrievalStrategy()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_build_query(self):
        class Incomplete(RetrievalStrategy):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        class Simple(RetrievalStrategy):
            async def build_query(self, context: dict) -> str:
                return "test query"

        s = Simple()
        assert s.top_k == 5   # default

    def test_extract_file_hints_empty(self):
        class S(RetrievalStrategy):
            async def build_query(self, context: dict) -> str:
                return ""

        assert S._extract_file_hints({}) == ""

    def test_extract_file_hints_limits_to_max(self):
        class S(RetrievalStrategy):
            async def build_query(self, context: dict) -> str:
                return ""

        hints = S._extract_file_hints({"file_paths": ["a.py", "b.py", "c.py", "d.py"]}, max_files=2)
        assert "a.py" in hints
        assert "d.py" not in hints

    def test_extract_frameworks_empty(self):
        class S(RetrievalStrategy):
            async def build_query(self, context: dict) -> str:
                return ""

        assert S._extract_frameworks({}) == ""

    def test_extract_language_default(self):
        class S(RetrievalStrategy):
            async def build_query(self, context: dict) -> str:
                return ""

        assert S._extract_language({}) == "Python"


# ---------------------------------------------------------------------------
# QAQueryStrategy
# ---------------------------------------------------------------------------


class TestQAQueryStrategy:
    strategy = QAQueryStrategy()

    def test_top_k_wider_than_default(self):
        assert self.strategy.top_k >= 6

    @pytest.mark.asyncio
    async def test_query_contains_test_terms(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert any(kw in q for kw in ("test", "assert", "mock", "fixture", "coverage"))

    @pytest.mark.asyncio
    async def test_query_includes_framework(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        # Frameworks should be mentioned
        assert "FastAPI" in query or "fastapi" in query.lower()

    @pytest.mark.asyncio
    async def test_query_non_empty(self):
        query = await self.strategy.build_query({})
        assert query.strip()

    @pytest.mark.asyncio
    async def test_query_includes_file_hints(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        assert "app/main.py" in query or "app/core.py" in query


# ---------------------------------------------------------------------------
# DevQueryStrategy
# ---------------------------------------------------------------------------


class TestDevQueryStrategy:
    strategy = DevQueryStrategy()

    @pytest.mark.asyncio
    async def test_query_contains_complexity_terms(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert any(kw in q for kw in ("complex", "refactor", "solid", "naming", "duplicate"))

    @pytest.mark.asyncio
    async def test_query_non_empty_empty_context(self):
        query = await self.strategy.build_query({})
        assert query.strip()

    @pytest.mark.asyncio
    async def test_query_mentions_language(self):
        query = await self.strategy.build_query({"primary_language": "TypeScript"})
        assert "TypeScript" in query


# ---------------------------------------------------------------------------
# ArchitectQueryStrategy
# ---------------------------------------------------------------------------


class TestArchitectQueryStrategy:
    strategy = ArchitectQueryStrategy()

    @pytest.mark.asyncio
    async def test_query_contains_architecture_terms(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert any(kw in q for kw in ("layer", "dependency", "import", "module", "boundary"))

    @pytest.mark.asyncio
    async def test_query_mentions_clean_architecture(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert "clean" in q or "hexagonal" in q or "architecture" in q

    @pytest.mark.asyncio
    async def test_query_non_empty_empty_context(self):
        query = await self.strategy.build_query({})
        assert query.strip()


# ---------------------------------------------------------------------------
# SREQueryStrategy
# ---------------------------------------------------------------------------


class TestSREQueryStrategy:
    strategy = SREQueryStrategy()

    @pytest.mark.asyncio
    async def test_query_contains_sre_terms(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert any(kw in q for kw in ("logging", "retry", "timeout", "health", "error"))

    @pytest.mark.asyncio
    async def test_query_contains_observability_terms(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert any(kw in q for kw in ("observ", "tracing", "metrics", "monitor"))

    @pytest.mark.asyncio
    async def test_query_non_empty_empty_context(self):
        query = await self.strategy.build_query({})
        assert query.strip()


# ---------------------------------------------------------------------------
# SecurityQueryStrategy
# ---------------------------------------------------------------------------


class TestSecurityQueryStrategy:
    strategy = SecurityQueryStrategy()

    def test_top_k_wide_for_security(self):
        assert self.strategy.top_k >= 7

    @pytest.mark.asyncio
    async def test_query_contains_security_terms(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert any(kw in q for kw in ("auth", "inject", "secret", "credential", "password"))

    @pytest.mark.asyncio
    async def test_query_contains_vulnerability_terms(self):
        query = await self.strategy.build_query(_BASE_CONTEXT)
        q = query.lower()
        assert any(kw in q for kw in ("sql injection", "xss", "http", "vulnerability"))

    @pytest.mark.asyncio
    async def test_query_non_empty_empty_context(self):
        query = await self.strategy.build_query({})
        assert query.strip()


# ---------------------------------------------------------------------------
# RetrievalStrategyRegistry
# ---------------------------------------------------------------------------


class TestRetrievalStrategyRegistry:
    def test_all_agents_registered(self):
        reg = RetrievalStrategyRegistry()
        for agent in AgentName:
            strategy = reg.get(agent)
            assert isinstance(strategy, RetrievalStrategy)

    def test_correct_strategy_types(self):
        reg = RetrievalStrategyRegistry()
        assert isinstance(reg.get(AgentName.SENIOR_QA), QAQueryStrategy)
        assert isinstance(reg.get(AgentName.SENIOR_DEVELOPER), DevQueryStrategy)
        assert isinstance(reg.get(AgentName.SENIOR_ARCHITECT), ArchitectQueryStrategy)
        assert isinstance(reg.get(AgentName.SENIOR_SRE), SREQueryStrategy)
        assert isinstance(reg.get(AgentName.SECURITY_EXPERT), SecurityQueryStrategy)

    def test_override_strategy(self):
        custom = MagicMock(spec=RetrievalStrategy)
        reg = RetrievalStrategyRegistry(overrides={AgentName.SENIOR_QA: custom})
        assert reg.get(AgentName.SENIOR_QA) is custom

    def test_runtime_register(self):
        reg = RetrievalStrategyRegistry()
        custom = MagicMock(spec=RetrievalStrategy)
        reg.register(AgentName.SENIOR_DEVELOPER, custom)
        assert reg.get(AgentName.SENIOR_DEVELOPER) is custom

    def test_registered_agents_returns_all(self):
        reg = RetrievalStrategyRegistry()
        assert set(reg.registered_agents) == set(AgentName)

    def test_unknown_agent_raises_key_error(self):
        reg = RetrievalStrategyRegistry()
        # Clear all strategies to force a miss
        reg._strategies.clear()
        with pytest.raises(KeyError):
            reg.get(AgentName.SENIOR_QA)


# ---------------------------------------------------------------------------
# AgentContextEnricher
# ---------------------------------------------------------------------------


class TestAgentContextEnricher:
    @pytest.mark.asyncio
    async def test_enrich_adds_retrieved_chunks(self):
        results = [_make_result(), _make_result()]
        svc = _mock_retrieval_service(results)
        enricher = AgentContextEnricher(svc)
        enriched = await enricher.enrich(AgentName.SENIOR_QA, _BASE_CONTEXT)
        assert enriched["retrieved_chunks"] == results

    @pytest.mark.asyncio
    async def test_enrich_adds_retrieval_query(self):
        svc = _mock_retrieval_service()
        enricher = AgentContextEnricher(svc)
        enriched = await enricher.enrich(AgentName.SENIOR_QA, _BASE_CONTEXT)
        assert isinstance(enriched["retrieval_query"], str)
        assert enriched["retrieval_query"].strip()

    @pytest.mark.asyncio
    async def test_enrich_does_not_mutate_original_context(self):
        svc = _mock_retrieval_service()
        enricher = AgentContextEnricher(svc)
        original = dict(_BASE_CONTEXT)
        await enricher.enrich(AgentName.SENIOR_QA, original)
        assert "retrieved_chunks" not in original
        assert "retrieval_query" not in original

    @pytest.mark.asyncio
    async def test_enrich_preserves_existing_context_keys(self):
        svc = _mock_retrieval_service()
        enricher = AgentContextEnricher(svc)
        ctx = {"repo_name": "test", "custom_key": "custom_value"}
        enriched = await enricher.enrich(AgentName.SENIOR_DEVELOPER, ctx)
        assert enriched["custom_key"] == "custom_value"
        assert enriched["repo_name"] == "test"

    @pytest.mark.asyncio
    async def test_enrich_uses_correct_top_k(self):
        svc = _mock_retrieval_service()
        enricher = AgentContextEnricher(svc)
        await enricher.enrich(AgentName.SENIOR_QA, _BASE_CONTEXT)
        _, call_kwargs = svc.search.call_args
        # QA strategy has top_k >= 6
        assert svc.search.call_args[1]["top_k"] >= 6 or svc.search.call_args[0][1] >= 6

    @pytest.mark.asyncio
    async def test_enrich_gracefully_handles_retrieval_error(self):
        svc = MagicMock()
        svc.search = AsyncMock(side_effect=RuntimeError("store unavailable"))
        enricher = AgentContextEnricher(svc)
        enriched = await enricher.enrich(AgentName.SENIOR_QA, _BASE_CONTEXT)
        assert enriched["retrieved_chunks"] == []

    @pytest.mark.asyncio
    async def test_enrich_empty_context(self):
        svc = _mock_retrieval_service([])
        enricher = AgentContextEnricher(svc)
        enriched = await enricher.enrich(AgentName.SECURITY_EXPERT, {})
        assert "retrieved_chunks" in enriched
        assert isinstance(enriched["retrieved_chunks"], list)

    @pytest.mark.asyncio
    async def test_all_agents_can_be_enriched(self):
        svc = _mock_retrieval_service([_make_result()])
        enricher = AgentContextEnricher(svc)
        for agent in AgentName:
            enriched = await enricher.enrich(agent, _BASE_CONTEXT)
            assert "retrieved_chunks" in enriched
            assert "retrieval_query" in enriched

    @pytest.mark.asyncio
    async def test_enrich_batch_returns_all_enriched(self):
        svc = _mock_retrieval_service([_make_result()])
        enricher = AgentContextEnricher(svc)
        contexts = [{"repo_name": f"repo-{i}"} for i in range(3)]
        results = await enricher.enrich_batch(AgentName.SENIOR_SRE, contexts)
        assert len(results) == 3
        for r in results:
            assert "retrieved_chunks" in r

    @pytest.mark.asyncio
    async def test_enrich_batch_preserves_per_context_keys(self):
        svc = _mock_retrieval_service([])
        enricher = AgentContextEnricher(svc)
        contexts = [{"repo_name": f"repo-{i}", "idx": i} for i in range(3)]
        results = await enricher.enrich_batch(AgentName.SENIOR_ARCHITECT, contexts)
        for i, r in enumerate(results):
            assert r["idx"] == i

    @pytest.mark.asyncio
    async def test_custom_registry_used(self):
        custom_strategy = MagicMock(spec=RetrievalStrategy)
        custom_strategy.top_k = 3
        custom_strategy.build_query = AsyncMock(return_value="custom query")
        registry = RetrievalStrategyRegistry(
            overrides={AgentName.SENIOR_QA: custom_strategy}
        )
        svc = _mock_retrieval_service()
        enricher = AgentContextEnricher(svc, registry)
        enriched = await enricher.enrich(AgentName.SENIOR_QA, _BASE_CONTEXT)
        assert enriched["retrieval_query"] == "custom query"
        custom_strategy.build_query.assert_called_once_with(_BASE_CONTEXT)
