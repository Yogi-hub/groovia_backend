# main.py
# FastAPI app entry point. Thin: app setup + router includes + lifespan.
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

# Windows-specific: psycopg's async driver does NOT work with the default ProactorEventLoop.
# Force the Selector loop policy BEFORE uvicorn creates its event loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import config
import db
from rate_limit import limiter
from routers import auth as auth_router
from routers import chat as chat_router
from routers import mentors as mentors_router


def _configure_logging() -> None:
    """Structured JSON logs in production, plain text in local dev.
    Render/Vercel log viewers handle JSON well; dev terminals are friendlier with plain."""
    if sys.platform == "win32":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        return
    try:
        from pythonjsonlogger.json import JsonFormatter  # type: ignore
    except ImportError:
        # Fallback path if the dep isn't installed yet.
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


_configure_logging()
logger = logging.getLogger("immigroov.api")


@asynccontextmanager
async def lifespan(api: FastAPI):
    import backend
    await backend.init_agent()
    try:
        yield
    finally:
        await backend.shutdown_agent()


api = FastAPI(title="Immigroov AI Career Engine", lifespan=lifespan)
api.state.limiter = limiter
api.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

api.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=600,  # cache OPTIONS preflight for 10 minutes
)


@api.get("/health")
def health():
    """Cheap liveness check — always returns 200 if the process is up."""
    return {"status": "ok"}


@api.get("/health/full")
async def health_full():
    """Deep health check. Verifies the DB is reachable. Used by Render / monitors."""
    checks = {"api": True, "db": False, "agent": False}
    try:
        # Sync supabase-py call → push to thread pool.
        await asyncio.to_thread(
            lambda: db.client().table("mentors").select("id").limit(1).execute()
        )
        checks["db"] = True
    except Exception:
        logger.exception("/health/full DB check failed")

    try:
        import backend
        checks["agent"] = backend.app is not None
    except Exception:
        pass

    ok = all(checks.values())
    return {"ok": ok, "checks": checks}


api.include_router(auth_router.router)
api.include_router(chat_router.router)
api.include_router(mentors_router.router)


if __name__ == "__main__":
    # On Windows, uvicorn.run() forces Proactor — but psycopg async REQUIRES Selector.
    # Work around by driving uvicorn.Server.serve() inside our own asyncio.run() with an
    # explicit loop_factory that returns a Selector loop. On non-Windows, uvicorn.run is fine.
    # timeout_graceful_shutdown gives in-flight requests up to 30s to finish before SIGKILL.
    if sys.platform == "win32":
        uvicorn_config = uvicorn.Config(
            api,
            host=config.HOST,
            port=config.PORT,
            loop="asyncio",
            timeout_graceful_shutdown=30,
        )
        server = uvicorn.Server(uvicorn_config)
        policy = asyncio.WindowsSelectorEventLoopPolicy()
        asyncio.run(server.serve(), loop_factory=policy.new_event_loop)
    else:
        uvicorn.run(
            api,
            host=config.HOST,
            port=config.PORT,
            timeout_graceful_shutdown=30,
        )
