"""Advanced retrieval tuning — agent-specific semantic query strategies.

Architecture
============

Each domain agent has distinct concerns.  Sending the same generic query to
the vector store for every agent wastes top-k budget and dilutes relevance.
This module provides:

* ``RetrievalStrategy`` (ABC)           — contract: build a semantic query from
                                          agent context → hand it to the
                                          :class:`RetrievalService`.
* Five concrete strategies, one per agent domain.
* ``AgentContextEnricher``             — orchestrates strategy → search →
                                          context injection so agents never
                                          touch the retrieval layer directly.
* ``RetrievalStrategyRegistry``        — maps :class:`AgentName` → strategy;
                                          injected as a singleton dependency.

Flow
====
::

    agent receives {repo_metadata, intelligence_data, …}
         │
         ▼
    AgentContextEnricher.enrich(agent_name, context)
         │
         ├─ 1. Lookup strategy from registry
         ├─ 2. strategy.build_query(context)      → query: str
         ├─ 3. RetrievalService.search(query, top_k=strategy.top_k)
         └─ 4. Inject SearchResult list into context["retrieved_chunks"]
                                          │
                                          ▼
                                    agent uses enriched context

Design rules
============
* No hardcoded keywords inside agents — only in strategies.
* Strategies are injected; agents depend on the ABC, not concrete classes.
* All public methods are ``async``.
* Strategies are pure functions of their context dict; they hold no state.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.domain.enums import AgentName
from app.infrastructure.embeddings.models import SearchResult
from app.infrastructure.embeddings.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

# Default top-k values are tuned per agent — some need wider context,
# others benefit from tighter, more focused recall.
_DEFAULT_TOP_K = 5


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class RetrievalStrategy(ABC):
    """Abstract base for agent-specific retrieval strategies.

    Subclasses encode *what* to search for; the :class:`AgentContextEnricher`
    handles *how* to execute the search and inject results.

    Attributes
    ----------
    top_k:
        Recommended maximum number of chunks to retrieve.  Each agent domain
        has a different sweet spot; override in concrete strategies.
    """

    top_k: int = _DEFAULT_TOP_K

    @abstractmethod
    async def build_query(self, context: dict[str, Any]) -> str:
        """Construct a semantic search query from the agent's execution context.

        Parameters
        ----------
        context:
            The agent's working context dict.  Common keys:

            * ``"repo_name"``       — repository name (``str``)
            * ``"file_paths"``      — list of relevant file paths (``list[str]``)
            * ``"primary_language"``— dominant language in the repo (``str``)
            * ``"frameworks"``      — detected frameworks / libraries (``list[str]``)
            * ``"summary"``         — high-level repo description (``str``)

            Any key may be absent; strategies must handle missing keys
            gracefully.

        Returns
        -------
        str
            A natural-language or code-style query suitable for cosine
            similarity search against embedded code chunks.
        """

    # ------------------------------------------------------------------
    # Shared helper utilities available to all strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_file_hints(context: dict[str, Any], max_files: int = 3) -> str:
        """Return a short string of the most relevant file paths for focus."""
        paths: list[str] = context.get("file_paths") or []
        if not paths:
            return ""
        sample = paths[:max_files]
        return " ".join(f"`{p}`" for p in sample)

    @staticmethod
    def _extract_frameworks(context: dict[str, Any]) -> str:
        """Return a comma-separated string of detected frameworks."""
        frameworks: list[str] = context.get("frameworks") or []
        return ", ".join(frameworks) if frameworks else ""

    @staticmethod
    def _extract_language(context: dict[str, Any]) -> str:
        return context.get("primary_language") or "Python"


# ---------------------------------------------------------------------------
# QA strategy
# ---------------------------------------------------------------------------


class QAQueryStrategy(RetrievalStrategy):
    """Retrieval strategy for the Senior QA Agent.

    Focuses on test coverage, assertion patterns, mock usage, test fixtures,
    and the relationship between source modules and their test counterparts.
    Wider top-k because QA needs both source and test context.
    """

    top_k: int = 8

    async def build_query(self, context: dict[str, Any]) -> str:
        language = self._extract_language(context)
        frameworks = self._extract_frameworks(context)
        file_hints = self._extract_file_hints(context)

        parts = [
            f"unit test coverage assertions pytest {language}",
            "test fixtures mock patch setUp tearDown",
            "missing test cases uncovered code paths",
            "assertion density test-to-source ratio",
        ]
        if frameworks:
            parts.append(f"testing {frameworks}")
        if file_hints:
            parts.append(f"tests for {file_hints}")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Developer strategy
# ---------------------------------------------------------------------------


class DevQueryStrategy(RetrievalStrategy):
    """Retrieval strategy for the Senior Developer Agent.

    Targets code quality signals: complexity hotspots, long functions, class
    design, naming conventions, duplicate logic, and adherence to SOLID.
    """

    top_k: int = 6

    async def build_query(self, context: dict[str, Any]) -> str:
        language = self._extract_language(context)
        frameworks = self._extract_frameworks(context)
        file_hints = self._extract_file_hints(context)

        parts = [
            f"complex function high cyclomatic complexity {language}",
            "god class long method too many parameters deep nesting",
            "code duplication repeated logic extract refactor",
            "naming conventions readability maintainability",
            "SOLID principles single responsibility open closed",
        ]
        if frameworks:
            parts.append(f"best practices {frameworks}")
        if file_hints:
            parts.append(f"implementation details {file_hints}")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Architect strategy
# ---------------------------------------------------------------------------


class ArchitectQueryStrategy(RetrievalStrategy):
    """Retrieval strategy for the Senior Architect Agent.

    Focuses on module boundaries, dependency direction, layer violations,
    circular imports, coupling metrics, and adherence to architectural
    patterns (Clean Architecture, hexagonal, etc.).
    """

    top_k: int = 7

    async def build_query(self, context: dict[str, Any]) -> str:
        language = self._extract_language(context)
        file_hints = self._extract_file_hints(context)

        parts = [
            f"module structure import dependency graph {language}",
            "layer violation domain infrastructure application boundary",
            "circular dependency coupling cohesion",
            "interface abstraction dependency inversion",
            "clean architecture hexagonal ports adapters",
        ]
        if file_hints:
            parts.append(f"architectural boundaries in {file_hints}")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# SRE strategy
# ---------------------------------------------------------------------------


class SREQueryStrategy(RetrievalStrategy):
    """Retrieval strategy for the Senior SRE Agent.

    Targets operational concerns: logging, error handling, retry logic,
    timeout configuration, health checks, resource cleanup, and
    observability instrumentation.
    """

    top_k: int = 6

    async def build_query(self, context: dict[str, Any]) -> str:
        language = self._extract_language(context)
        frameworks = self._extract_frameworks(context)
        file_hints = self._extract_file_hints(context)

        parts = [
            f"logging error handling exception retry timeout {language}",
            "health check liveness readiness probe",
            "resource leak connection pool cleanup context manager",
            "observability tracing metrics instrumentation",
            "graceful shutdown signal handling",
        ]
        if frameworks:
            parts.append(f"reliability patterns {frameworks}")
        if file_hints:
            parts.append(f"operational concerns in {file_hints}")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Security strategy
# ---------------------------------------------------------------------------


class SecurityQueryStrategy(RetrievalStrategy):
    """Retrieval strategy for the Security Expert Agent.

    Focuses on authentication, authorisation, input validation, injection
    vulnerabilities, secret exposure, insecure HTTP usage, and dependency
    security.
    """

    top_k: int = 8  # security needs broad recall to catch subtle issues

    async def build_query(self, context: dict[str, Any]) -> str:
        language = self._extract_language(context)
        frameworks = self._extract_frameworks(context)
        file_hints = self._extract_file_hints(context)

        parts = [
            f"authentication authorization JWT token validation {language}",
            "SQL injection command injection XSS input sanitization",
            "hardcoded secret API key password credential exposure",
            "insecure HTTP plaintext sensitive data transmission",
            "dependency vulnerability outdated package requirements",
        ]
        if frameworks:
            parts.append(f"security vulnerabilities {frameworks}")
        if file_hints:
            parts.append(f"security review of {file_hints}")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class RetrievalStrategyRegistry:
    """Maps :class:`AgentName` values to their :class:`RetrievalStrategy`.

    Designed as a singleton — create once and inject everywhere.

    Usage
    -----
    ::

        registry = RetrievalStrategyRegistry()
        strategy = registry.get(AgentName.SENIOR_QA)
    """

    def __init__(
        self,
        overrides: dict[AgentName, RetrievalStrategy] | None = None,
    ) -> None:
        self._strategies: dict[AgentName, RetrievalStrategy] = {
            AgentName.SENIOR_QA: QAQueryStrategy(),
            AgentName.SENIOR_DEVELOPER: DevQueryStrategy(),
            AgentName.SENIOR_ARCHITECT: ArchitectQueryStrategy(),
            AgentName.SENIOR_SRE: SREQueryStrategy(),
            AgentName.SECURITY_EXPERT: SecurityQueryStrategy(),
        }
        if overrides:
            self._strategies.update(overrides)

    def get(self, agent_name: AgentName) -> RetrievalStrategy:
        """Return the strategy for *agent_name*.

        Raises
        ------
        KeyError
            If no strategy is registered for *agent_name*.  This is a
            programming error — all :class:`AgentName` values must be covered.
        """
        try:
            return self._strategies[agent_name]
        except KeyError:
            raise KeyError(
                f"No retrieval strategy registered for agent '{agent_name}'. "
                "Register one via the overrides parameter."
            ) from None

    def register(self, agent_name: AgentName, strategy: RetrievalStrategy) -> None:
        """Register or replace a strategy at runtime."""
        self._strategies[agent_name] = strategy

    @property
    def registered_agents(self) -> list[AgentName]:
        return list(self._strategies.keys())


# ---------------------------------------------------------------------------
# Context enricher
# ---------------------------------------------------------------------------

_RETRIEVED_CHUNKS_KEY = "retrieved_chunks"
_RETRIEVAL_QUERY_KEY = "retrieval_query"


class AgentContextEnricher:
    """Inject semantically relevant code chunks into an agent's context dict.

    This class is the single integration point between the application layer
    (agents) and the infrastructure layer (vector store / embedding service).
    Agents call :meth:`enrich`; they never import from ``infrastructure``
    directly.

    Parameters
    ----------
    retrieval_service:
        The shared :class:`RetrievalService` backed by the indexed codebase.
    registry:
        :class:`RetrievalStrategyRegistry` mapping agents to query strategies.
        If omitted a default registry (all five strategies) is created.

    Usage
    -----
    ::

        enricher = AgentContextEnricher(retrieval_service, registry)
        enriched_context = await enricher.enrich(AgentName.SENIOR_QA, context)
        # enriched_context["retrieved_chunks"] → list[SearchResult]
        # enriched_context["retrieval_query"]  → str (for debugging)
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        registry: RetrievalStrategyRegistry | None = None,
    ) -> None:
        self._service = retrieval_service
        self._registry = registry or RetrievalStrategyRegistry()

    async def enrich(
        self,
        agent_name: AgentName,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a shallow copy of *context* enriched with retrieved chunks.

        The original *context* dict is **not** mutated.

        Parameters
        ----------
        agent_name:
            Identifies which strategy to use.
        context:
            Agent's working context dict (repo metadata, intelligence data,
            etc.).  See :meth:`RetrievalStrategy.build_query` for expected keys.

        Returns
        -------
        dict
            Copy of *context* with two additional keys:

            * ``"retrieved_chunks"`` — ``list[SearchResult]`` ordered by
              descending cosine similarity.
            * ``"retrieval_query"``  — ``str`` query that produced the results
              (useful for debugging and prompt logging).

        Notes
        -----
        * If the retrieval service has no indexed documents an empty list is
          returned gracefully — agents must handle absent chunks.
        * Exceptions from the retrieval service are caught and logged; the
          original context is returned with an empty chunks list so the agent
          can still run (degraded mode).
        """
        strategy = self._registry.get(agent_name)
        query = await strategy.build_query(context)

        try:
            results: list[SearchResult] = await self._service.search(
                query, top_k=strategy.top_k
            )
        except Exception as exc:
            logger.error(
                "retrieval.enrich_failed",
                extra={
                    "agent": agent_name.value,
                    "error": str(exc),
                },
            )
            results = []

        logger.info(
            "retrieval.enrich_complete",
            extra={
                "agent": agent_name.value,
                "query_length": len(query),
                "chunks_returned": len(results),
            },
        )

        return {
            **context,
            _RETRIEVED_CHUNKS_KEY: results,
            _RETRIEVAL_QUERY_KEY: query,
        }

    async def enrich_batch(
        self,
        agent_name: AgentName,
        contexts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Enrich multiple contexts with the same agent strategy.

        Useful when running the same agent against multiple files or modules
        in one pass.  Each context is enriched independently.
        """
        import asyncio
        tasks = [self.enrich(agent_name, ctx) for ctx in contexts]
        return list(await asyncio.gather(*tasks))
