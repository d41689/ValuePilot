import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.api import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    job_worker = None
    if settings.EDGAR_SCHEDULER_ENABLED:
        from app.core.db import SessionLocal
        from app.services.scheduler import create_scheduler
        scheduler = create_scheduler(SessionLocal)
        scheduler.start()
        logger.info("EDGAR quarterly scheduler started")
    if settings.THIRTEENF_JOB_WORKER_ENABLED and not app.dependency_overrides:
        from app.core.db import SessionLocal
        from app.services.thirteenf_job_worker import ThirteenFJobWorker

        job_worker = ThirteenFJobWorker(SessionLocal)
        job_worker.start()
        logger.info("13F admin job worker started")

        # Issue #40: if a system-level start quarter is configured, enqueue
        # quarterly_pipeline jobs for every missing quarter in the range.
        # Idempotent — succeeded quarters are skipped. Wrapped in try/except
        # so a reconcile failure never blocks API startup.
        if settings.THIRTEENF_START_QUARTER:
            try:
                from app.services.thirteenf_start_quarter import (
                    reconcile_start_quarter_coverage,
                )

                with SessionLocal() as boot_db:
                    result = reconcile_start_quarter_coverage(boot_db)
                logger.info(
                    "Start-quarter reconcile: enqueued=%d skipped_existing=%d skipped_conflict=%d",
                    len(result.get("enqueued", [])),
                    len(result.get("skipped_existing", [])),
                    len(result.get("skipped_conflict", [])),
                )
            except Exception:
                logger.exception("Start-quarter reconcile failed; continuing startup")
    yield
    if job_worker is not None:
        job_worker.stop()
        logger.info("13F admin job worker stopped")
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("EDGAR scheduler stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Financial Analysis Engine API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "users", "description": "Operations with users."},
    ],
)

origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {"message": "Welcome to ValuePilot API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}
