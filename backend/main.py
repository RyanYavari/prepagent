import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

# Libraries that log request URLs/params at INFO (httpx) or payload details at
# lower levels. Kept at WARNING so enabling INFO for our code never exposes them.
_QUIET_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "hpack",
    "openai",
    "anthropic",
    "langsmith",
    "supabase",
    "postgrest",
)


def configure_logging() -> None:
    """
    Make INFO logs from agents/services visible, once.

    Attaches a handler to the root logger only if none exists (uvicorn installs its
    own handlers on its own non-propagating loggers, so its access log is not
    duplicated here). Never log resume text, chunk content, tokens or API keys:
    log ids and counts only.
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    root.setLevel(logging.INFO)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


configure_logging()


def _startup_sweep() -> None:
    """Fail briefings orphaned on `running` by a previous process. Never raises."""
    try:
        from services.briefings import sweep_stale_running
        from services.supabase_client import get_service_client

        sweep_stale_running(get_service_client())
    except Exception:
        logging.getLogger(__name__).exception("Startup stale briefing sweep failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Sweep stale runs, then start the optional calendar poller (off unless set)."""
    await asyncio.to_thread(_startup_sweep)
    from routers.calendar import _get_supabase
    from services.calendar_poller import poll_interval_minutes, run_poller

    interval = poll_interval_minutes()
    task = (
        asyncio.create_task(run_poller(_get_supabase, interval)) if interval else None
    )
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="PrepAgent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# FastAPI's default 422 body includes `input`. For a 12k-character pasted job
# description that would reflect it (and any recruiter details in it) back in the
# response. Two cases leak it: errors on the field itself, and errors whose `input`
# is the whole request body (a "missing company" error carries the entire body, and
# so does a non-object body). Both are stripped; errors on a scalar field such as an
# unsafe `company` still report the value the user typed.
_NO_ECHO_FIELDS = {"job_description"}


def _echoes_body(error: dict) -> bool:
    loc = error.get("loc") or ()
    if loc and loc[-1] in _NO_ECHO_FIELDS:
        return True
    return tuple(loc) == ("body",) or isinstance(error.get("input"), (dict, list))


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(_request: Request, exc: RequestValidationError):
    errors = [
        {k: v for k, v in e.items() if k != "input"} if _echoes_body(e) else e
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


from routers.auth import router as auth_router
from routers.calendar import router as calendar_router
from routers.research import router as research_router

app.include_router(auth_router)
app.include_router(calendar_router)
app.include_router(research_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
