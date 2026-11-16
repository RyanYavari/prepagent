"""Log failures without echoing what the failure carried.

Database and provider error messages can include user-supplied text: Postgres puts
the whole failing row in the error detail, and provider errors may quote the request.
`logger.exception` would write that message and traceback to the log, so on paths that
handle user text we log the exception class instead.
"""

import logging


def log_failure(logger: logging.Logger, message: str, exc: BaseException) -> None:
    logger.error("%s (%s)", message, type(exc).__name__)
