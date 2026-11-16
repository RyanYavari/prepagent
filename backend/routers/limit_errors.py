"""Map briefing limit errors to HTTP responses (shared by the research and calendar routers)."""

from fastapi import HTTPException, status

from services.limits import (
    BriefingBlockedError,
    BriefingLimitError,
    BriefingsDisabledError,
)


def briefing_blocked_http(exc: BriefingBlockedError) -> HTTPException:
    if isinstance(exc, BriefingsDisabledError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    headers = None
    if isinstance(exc, BriefingLimitError):
        headers = {"Retry-After": str(exc.retry_after)}
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=str(exc),
        headers=headers,
    )
