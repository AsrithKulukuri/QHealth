import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, select
from .api import datasets, experiments, models, pipeline, quantum, training
from .api.middleware import BodyLimitMiddleware
from .api.security import authorize
from .api.schemas import ExperimentOut
from .config import DISCLAIMER, get_settings
from .database import init_db, session_scope
from .jobs.manager import manager
from .quantum.backends import availability
from .storage.entities import Dataset, Experiment, Job, ModelRecord
from .storage.repository import recent
from .utils.errors import AppError

settings = get_settings()
logger = logging.getLogger("qhealth")

class SafeJSONFormatter(logging.Formatter):
    def format(self, record):
        # Application calls supply only fixed messages, opaque IDs and exception types.
        return json.dumps({"level": record.levelname, "logger": record.name, "event": record.getMessage()})

handler = logging.StreamHandler()
handler.setFormatter(SafeJSONFormatter())
logger.handlers = [handler]
logger.setLevel(settings.log_level.upper())
logger.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as exc:
        logger.error("init_db_error: %s", exc)
    try:
        manager.start()
    except Exception as exc:
        logger.error("manager_start_error: %s", exc)
    logger.info("application_started mode=single_workstation_research")
    try:
        yield
    finally:
        try:
            manager.stop()
        except Exception:
            pass

app = FastAPI(title="EntangleX Q-Health", version="0.1.0", description=DISCLAIMER, lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware, max_bytes=settings.upload_limit + 65536)

# Allow Vercel deployments, localhost, and custom domains
allowed_hosts = [s.strip() for s in settings.trusted_hosts.split(",") if s.strip()]
if "*" not in allowed_hosts:
    allowed_hosts.extend(["*.vercel.app", "vercel.app", "*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)

@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error("request_failure request_id=%s exception_type=%s message=%s", request.state.request_id, type(exc).__name__, str(exc))
        response = JSONResponse({
            "error": {
                "code": "internal_error",
                "message": f"{type(exc).__name__}: {str(exc)}",
                "request_id": request.state.request_id
            }
        }, status_code=500)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

@app.exception_handler(AppError)
async def application_error(request: Request, exc: AppError):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message, "request_id": getattr(request.state, "request_id", None)}}, status_code=exc.status)

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = [{"location": [str(v) for v in err["loc"]], "type": err["type"]} for err in exc.errors()]
    return JSONResponse({"error": {"code": "validation_error", "message": "Request validation failed.", "fields": fields, "request_id": getattr(request.state, "request_id", None)}}, status_code=422)

@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": {"code": "http_error", "message": exc.detail or "The requested operation is unavailable.", "request_id": getattr(request.state, "request_id", None)}}, status_code=exc.status_code)

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("unexpected_error request_id=%s exception_type=%s: %s", getattr(request.state, "request_id", None), type(exc).__name__, str(exc))
    return JSONResponse({"error": {"code": "internal_error", "message": f"{type(exc).__name__}: {str(exc)}", "request_id": getattr(request.state, "request_id", None)}}, status_code=500)

@app.get("/api/health", tags=["health"])
def health():
    db_status = "local"
    if settings.is_postgres_enabled:
        try:
            from sqlalchemy import text
            from .database import engine
            with engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
            db_status = "connected (postgresql)"
        except Exception as exc:
            db_status = f"unreachable: {type(exc).__name__}"
    return {
        "status": "ok",
        "version": "0.1.0",
        "mode": "production" if settings.is_postgres_enabled else "local-prototype",
        "database": db_status,
        "supabase_storage": "configured" if settings.is_supabase_storage_enabled else "unconfigured",
        "authentication_required": bool(settings.api_token),
        "quantum": availability(),
        "disclaimer": DISCLAIMER,
    }

api = APIRouter(prefix="/api", dependencies=[Depends(authorize)])
for router in [datasets.router, pipeline.router, training.router, models.router, experiments.router, quantum.router]:
    api.include_router(router)

@api.get("/summary", tags=["dashboard"])
def summary():
    try:
        with session_scope() as session:
            counts = {
                "datasets": session.scalar(select(func.count()).select_from(Dataset)) or 0,
                "experiments": session.scalar(select(func.count()).select_from(Experiment)) or 0,
                "ready_models": session.scalar(select(func.count()).select_from(ModelRecord).where(ModelRecord.status == "ready")) or 0,
                "active_jobs": session.scalar(select(func.count()).select_from(Job).where(Job.status.in_(["queued", "running", "cancel_requested"]))) or 0,
            }
            experiments_recent = [ExperimentOut.model_validate(e).model_dump(mode="json") for e in recent(session, Experiment, 5)]
        return {"counts": counts, "recent_experiments": experiments_recent, "disclaimer": DISCLAIMER}
    except Exception as exc:
        logger.error("summary_fetch_error: %s", exc)
        return {
            "counts": {"datasets": 0, "experiments": 0, "ready_models": 0, "active_jobs": 0},
            "recent_experiments": [],
            "disclaimer": DISCLAIMER,
            "warning": f"Database temporarily unavailable: {type(exc).__name__}",
        }

app.include_router(api)

