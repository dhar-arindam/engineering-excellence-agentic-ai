"""Application-level exception hierarchy."""
from __future__ import annotations


class AppError(Exception):
    """Base class for all application errors."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(f"{resource} '{resource_id}' not found.", status_code=404)


class ValidationError(AppError):
    """Raised for invalid input that passes schema validation but fails business rules."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, status_code=422)


class AgentExecutionError(AppError):
    """Raised when a domain agent fails to produce a valid finding."""

    def __init__(self, agent_name: str, reason: str) -> None:
        super().__init__(
            f"Agent '{agent_name}' failed: {reason}", status_code=500
        )


class LLMError(AppError):
    """Raised when the LLM adapter encounters an unrecoverable error."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"LLM error: {detail}", status_code=502)


class RepositoryAccessError(AppError):
    """Raised when the repository cannot be accessed or parsed."""

    def __init__(self, target: str, reason: str) -> None:
        super().__init__(
            f"Cannot access repository '{target}': {reason}", status_code=422
        )


class ScanCancelledError(AppError):
    """Raised inside ScanOrchestrator when a cancellation flag is detected in Redis."""

    def __init__(self, scan_id: str) -> None:
        super().__init__(f"Scan '{scan_id}' was cancelled.", status_code=409)


class ScanAlreadyRunningError(AppError):
    """Raised when a second scan is submitted for a repository that already has one running."""

    def __init__(self, repository_id: str) -> None:
        super().__init__(
            f"A scan is already running for repository '{repository_id}'.",
            status_code=409,
        )
