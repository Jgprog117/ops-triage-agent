import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.db.database import init_database, close_database
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
async def lifespan(app: FastAPI):
    set_start_time(time.time())
    logger.info("Starting ai& Ops Agent...")

    await init_database()
    await seed_host_data()
    logger.info("Database ready")

    await asyncio.to_thread(init_knowledge_base)
    logger.info("Knowledge base ready")

    set_triage_callback(triage_alert)
    simulator_task = asyncio.create_task(alert_simulator())
    logger.info("Alert simulator started")

    logger.info("ai& Ops Agent is running — open http://localhost:3000")

    yield

    simulator_task.cancel()
    try:
        await simulator_task
    except asyncio.CancelledError:
        pass
    await close_database()
    await llm.close()
    logger.info("ai& Ops Agent shut down")


app = FastAPI(
    title="ai& Ops Agent",
    description="AI-powered data center incident triage system",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(stream.router)
app.include_router(alerts.router)
app.include_router(incidents.router)
app.include_router(knowledge.router)
app.include_router(stats.router)
app.include_router(config.router)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "aiand-ops-agent"}


@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
