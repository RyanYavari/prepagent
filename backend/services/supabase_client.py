"""
Supabase client factory with bounded timeouts, and a retrying `execute`.

Every module builds its client through `create_client` here so no database call can
wait on the library default (120s). `execute` additionally retries connection-class
failures (DNS, refused, connect timeout), where the request never reached the
server, so it is safe for inserts too. Read/write timeouts are not retried: the
server may already have applied the change.
"""

import os
from typing import Any

import httpx
from supabase import create_client as _create_client
from supabase.lib.client_options import SyncClientOptions

from services.net_config import env_float, env_int, retry_call

_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout)


def create_client(url: str | None, key: str | None) -> Any:
    timeout = env_float("SUPABASE_TIMEOUT_SECONDS")
    options = SyncClientOptions(
        postgrest_client_timeout=timeout,
        storage_client_timeout=int(timeout),
        function_client_timeout=int(timeout),
    )
    return _create_client(url or "", key or "", options=options)


def get_service_client() -> Any:
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


def execute(builder: Any) -> Any:
    """Run a PostgREST query builder, retrying connection-class failures."""
    return retry_call(
        builder.execute,
        retries=env_int("SUPABASE_MAX_RETRIES"),
        retry_on=_RETRYABLE,
        label="supabase request",
    )
