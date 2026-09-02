"""
LECTIO — FastAPI Application Entry Point
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from db.base import engine
import db.models  # registers ALL ORM models
from db.bootstrap import ensure_admin_user
from utils.logging_config import setup_logging

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} [{settings.app_env}]")
    from db.base import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified.")
    await ensure_admin_user()
    logger.info(f"{settings.app_name} ready.")
    yield
    logger.info(f"{settings.app_name} shutting down.")
    await engine.dispose()


app = FastAPI(
    title="LECTIO API",
    description="AI Course Curation Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://frontend:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.v1.middleware.audit_logger import AuditMiddleware
app.add_middleware(AuditMiddleware)

@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.perf_counter()
    r  = await call_next(request)
    r.headers["X-Process-Time-Ms"] = f"{(time.perf_counter()-t0)*1000:.2f}"
    return r

@app.exception_handler(Exception)
async def global_exc(request: Request, exc: Exception):
    logger.error(f"Unhandled: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})

@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy", "app": settings.app_name, "version": "1.0.0"}

# ── Routers ───────────────────────────────────────────────────────────────────
from api.v1.routes import auth, courses, artifacts, admin
from api.v1.routes.workflow_routes import runs_router, reports_router, approvals_router

app.include_router(auth.router,          prefix="/api/v1/auth",     tags=["Authentication"])
app.include_router(courses.router,       prefix="/api/v1/courses",  tags=["Courses"])
app.include_router(artifacts.router,     prefix="/api/v1/courses",  tags=["Artefacts"])
app.include_router(admin.router,         prefix="/api/v1/admin",    tags=["Admin"])
app.include_router(runs_router,          prefix="/api/v1",          tags=["Agent Runs"])
app.include_router(reports_router,       prefix="/api/v1",          tags=["Reports"])
app.include_router(approvals_router,     prefix="/api/v1",          tags=["Approvals"])
