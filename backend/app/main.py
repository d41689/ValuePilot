import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.api import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Live EDGAR access must route through Rate Guard (the shared egress
    # limiter). Refuse to start a live-mode api without it — a per-process
    # limiter cannot bound the combined dev+prod egress rate and risks an
    # EDGAR IP ban. Use EDGAR_FETCH_MODE=replay for tests / offline runs.
    if settings.EDGAR_FETCH_MODE == "live" and not (settings.RATE_GUARD_URL or "").strip():
        raise RuntimeError(
            "EDGAR_FETCH_MODE=live requires RATE_GUARD_URL — live EDGAR access "
            "must go through Rate Guard. Set RATE_GUARD_URL, or use "
            "EDGAR_FETCH_MODE=replay. See rate-guard/README.md."
        )

    # Seed the curated manager universe BEFORE the scheduler or the job worker
    # can act on it: ingestion selects managers on `match_status == 'confirmed'`,
    # so a pipeline job that ran first would ingest an empty universe.
    #
    # Deliberately NOT wrapped in try/except, unlike the start-quarter reconcile
    # below. That reconcile is idempotent and retried on the next boot, so
    # swallowing its failure costs nothing. The manager seed is the opposite: an
    # API that starts with an empty or partial universe ingests no filings and
    # scores nothing, silently. `test_the_curated_seed_file_is_valid` keeps a
    # malformed seed file out of the image, so failing loud here cannot
    # crash-loop prod on anything CI could have caught.
    if settings.MANAGER_SEED_ON_STARTUP:
        from app.core.db import SessionLocal
        from app.services.manager_seed_startup import run_startup_manager_seed

        run_startup_manager_seed(SessionLocal)

    scheduler = None
    research_notification_scheduler = None
    job_worker = None
    if settings.EDGAR_SCHEDULER_ENABLED:
        from app.core.db import SessionLocal
        from app.services.scheduler import create_scheduler
        scheduler = create_scheduler(SessionLocal)
        scheduler.start()
        logger.info("EDGAR quarterly scheduler started")
    if settings.RESEARCH_NOTIFICATION_SCHEDULER_ENABLED:
        from app.core.db import SessionLocal
        from app.services.scheduler import create_research_notification_scheduler

        research_notification_scheduler = create_research_notification_scheduler(
            SessionLocal
        )
        research_notification_scheduler.start()
        logger.info("Research notification scheduler started")
    if settings.THIRTEENF_JOB_WORKER_ENABLED and not app.dependency_overrides:
        from app.core.db import SessionLocal
        from app.services.thirteenf_job_worker import ThirteenFJobWorker

        job_worker = ThirteenFJobWorker(SessionLocal)
        job_worker.start()
        logger.info("13F admin job worker started")

        # Issue #40: if a system-level start quarter is configured, enqueue
        # quarterly_pipeline jobs for every missing quarter in the range.
        # Idempotent — quarters with complete six-stage manifests are skipped. Wrapped in try/except
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
    if research_notification_scheduler is not None:
        research_notification_scheduler.shutdown(wait=False)
        logger.info("Research notification scheduler stopped")


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


# Security response headers. Next.js `headers()` (frontend/next.config.js)
# decorates page routes but NOT the `/api/*` paths Next rewrites to this API,
# so the API sets its own — coverage is then uniform site-wide. Keep these
# values in sync with `frontend/next.config.js`.
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers[key] = value
    return response


app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {"message": "Welcome to ValuePilot API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}
