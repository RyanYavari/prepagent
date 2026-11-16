import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the optional calendar poller (off unless the interval is set)."""
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

from routers.auth import router as auth_router
from routers.calendar import router as calendar_router
from routers.research import router as research_router

app.include_router(auth_router)
app.include_router(calendar_router)
app.include_router(research_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
