"""One-off: revoke stored sign-in Google tokens at Google, then scrub them.

Run from backend/ AFTER deploying the code that stops storing tokens and BEFORE
applying migration 005 (which refuses to run while any token remains):

    python -m scripts.revoke_stored_tokens

Revocation is best effort. Every row is scrubbed whether or not Google confirmed
the revoke (a token Google already invalidated reports as unconfirmed). Token
values are never printed or logged; failures log only the exception type.
See specs/signin-token-removal.md.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

BATCH_SIZE = 200
_COLUMNS = ("google_refresh_token", "google_access_token")


async def run(
    supabase: Any,
    revoke: Callable[[str], Awaitable[bool]] | None = None,
) -> dict[str, int]:
    if revoke is None:
        from services.google_auth import revoke_token

        revoke = revoke_token

    summary = {"scanned": 0, "revoked": 0, "unconfirmed": 0, "scrubbed": 0}
    start = 0
    while True:
        # Paging by position is stable: rows are scrubbed in place, never removed.
        rows = (
            supabase.table("users")
            .select("id, google_refresh_token, google_access_token")
            .order("id")
            .range(start, start + BATCH_SIZE - 1)
            .execute()
            .data
        )
        if not rows:
            break
        start += len(rows)
        for row in rows:
            summary["scanned"] += 1
            # The refresh token's revocation also invalidates its access tokens.
            token = row.get("google_refresh_token") or row.get("google_access_token")
            if not token:
                continue
            try:
                confirmed = await revoke(token)
            except Exception as e:  # noqa: BLE001 - best effort; scrub regardless
                logger.warning(
                    "revoke failed for user %s: %s", row["id"], type(e).__name__
                )
                confirmed = False
            summary["revoked" if confirmed else "unconfirmed"] += 1
            supabase.table("users").update({c: None for c in _COLUMNS}).eq(
                "id", row["id"]
            ).execute()
            summary["scrubbed"] += 1
    return summary


def main() -> None:
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv()
    supabase = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    )
    summary = asyncio.run(run(supabase))
    print(
        "scanned={scanned} revoked={revoked} unconfirmed={unconfirmed} "
        "scrubbed={scrubbed}".format(**summary)
    )


if __name__ == "__main__":
    main()
