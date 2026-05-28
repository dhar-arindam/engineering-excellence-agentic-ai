"""Auth endpoints."""
from __future__ import annotations

import getpass

from fastapi import APIRouter

from app.api.schemas import LocalUserResponse
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.get(
    "/local-user",
    response_model=LocalUserResponse,
    summary="Get the local system user",
    description=(
        "Returns the OS-level username of the process running the API server.  "
        "Useful in local development environments as a lightweight identity source."
    ),
    operation_id="get_local_user",
    responses={200: {"description": "Local user info."}},
)
async def get_local_user() -> LocalUserResponse:
    username = getpass.getuser()
    logger.info("api.get_local_user", username=username)
    return LocalUserResponse(
        id=username,
        name=username,
        email=f"{username}@localhost",
    )
