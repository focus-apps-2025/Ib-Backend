from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
from loguru import logger
import sys

from app.config.settings import settings
from app.config.database import connect_to_mongo, close_mongo_connection

# ── Import Middleware ────────────────────────────────────────────────────────
from app.middleware.logging import LoggingMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# ── Configure Loguru ─────────────────────────────────────────────────────────
logger.remove()
logger.add(sys.stdout, colorize=True, format="<green>{time:HH:mm:ss}</green> | "
           "<level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    await connect_to_mongo()

    # Create uploads directory
    Path(settings.UPLOAD_DIR).mkdir(exist_ok=True)

    # Seed initial data if needed
    try:
        from app.utils.seeder import seed_initial_data
        await seed_initial_data()
    except Exception as e:
        logger.warning(f"Seeder warning: {e}")

    yield

    await close_mongo_connection()
    logger.info("👋 Application shutdown complete")


# ── Create FastAPI app ───────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="VQS API - Vehicle Quality Survey: survey upload, complaint analysis & dashboard platform",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── Add Middleware ──────────────────────────────────────────────────────────
# CORS first
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware (order matters - execute in reverse order of addition)
app.add_middleware(LoggingMiddleware)      # Log all requests/responses
app.add_middleware(RequestIDMiddleware)    # Add unique request ID
app.add_middleware(RateLimitMiddleware, calls_per_minute=60)  # Rate limiting

# ── Register API Routers ─────────────────────────────────────────────────────
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router
from app.routes.regions import router as regions_router
from app.routes.countries import router as countries_router
from app.routes.ib_versions import router as ib_versions_router
from app.routes.upload import router as upload_router
from app.routes.responses import router as responses_router
from app.routes.issues import router as issues_router
from app.routes.dashboard import router as dashboard_router
from app.routes.comparison import router as comparison_router
from app.routes.activity_logs import router as activity_logs_router
from app.routes.market_feedback import router as market_feedback_router

API_PREFIX = "/api"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(regions_router, prefix=API_PREFIX)
app.include_router(countries_router, prefix=API_PREFIX)
app.include_router(ib_versions_router, prefix=API_PREFIX)
app.include_router(upload_router, prefix=API_PREFIX)
app.include_router(responses_router, prefix=API_PREFIX)
app.include_router(issues_router, prefix=API_PREFIX)
app.include_router(dashboard_router, prefix=API_PREFIX)
app.include_router(comparison_router, prefix=API_PREFIX)
app.include_router(activity_logs_router, prefix=API_PREFIX)
app.include_router(market_feedback_router, prefix=API_PREFIX)



@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "app": settings.APP_NAME,
    }