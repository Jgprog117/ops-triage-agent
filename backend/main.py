"""FastAPI application entry point for the Ops Triage Agent.

Wires together the alert simulator, the LLM-driven triage agent, the SSE
broadcaster, and the dashboard frontend in a single ASGI application.
The lifespan context performs all startup work — database init, host seeding,
RAG index build, and simulator launch — and tears the same resources down
when the server stops.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.db.database import init_database, close_database, get_db
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.db.seed import seed_host_data
from backend.knowledge.rag import init_knowledge_base
from backend.simulator.engine import alert_simulator, set_triage_callback
from backend.agent.triage import triage_alert
from backend.llm.client import llm
from backend.routes import alerts, incidents, knowledge, stream, stats, config
from backend.routes.stats import set_start_time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manages startup and shutdown for the application.

    On startup, validates configuration, initializes the database, seeds host
    inventory, builds the RAG knowledge base, registers the triage callback,
    and launches the alert simulator as a background task. On shutdown, the
    simulator is cancelled and all clients (DB, HTTP) are closed cleanly.

    Args:
        app: The FastAPI application instance being managed. Unused, but
            required by the lifespan context-manager protocol.

    Yields:
        None. Control is yielded back to FastAPI between startup and shutdown.
    """
    set_start_time(time.time())
    logger.info("Starting Ops Triage Agent...")

    # Validate configuration before anything else
    settings.validate_required()

    if settings.OPS_AGENT_API_KEY == "demo-key-change-me":
        logger.warning("OPS_AGENT_API_KEY is using the demo default — change it for production")

    await init_database()
    await seed_host_data()
    logger.info("Database ready")

    await asyncio.to_thread(init_knowledge_base)
    logger.info("Knowledge base ready")

    set_triage_callback(triage_alert)
    simulator_task = asyncio.create_task(alert_simulator())
    logger.info("Alert simulator started")

    logger.info("Ops Triage Agent is running — dashboard available on the mapped port")

    yield

    simulator_task.cancel()
    try:
        await asyncio.wait_for(simulator_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    await close_database()
    await llm.close()
    logger.info("Ops Triage Agent shut down")


app = FastAPI(
    title="Ops Triage Agent",
    description="AI-powered data center incident triage system",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)

app.include_router(stream.router)
app.include_router(alerts.router)
app.include_router(incidents.router)
app.include_router(knowledge.router)
app.include_router(stats.router)
app.include_router(config.router)


@app.get("/health")
async def health_check() -> dict:
    """Returns a liveness/readiness summary for the service.

    Currently exercises the database with a trivial ``SELECT 1`` to confirm
    the connection is open. The HTTP status code is always 200 — callers
    should inspect the ``status`` field for ``healthy`` vs ``degraded``.

    Returns:
        A dict with three keys: ``status`` (``healthy`` or ``degraded``),
        ``service`` (the service name), and ``checks`` (a per-dependency
        status map).
    """
    checks = {"database": "ok"}
    try:
        db = await get_db()
        await db.execute("SELECT 1")
    except Exception:
        checks["database"] = "error"
    status = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "service": "ops-triage-agent", "checks": checks}


@app.get("/")
async def serve_frontend() -> FileResponse:
    """Serves the single-page dashboard at the root path.

    Returns:
        A FileResponse pointing at ``frontend/index.html``.
    """
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
