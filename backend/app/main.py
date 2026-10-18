"""Version 2 HTTP surface: health plus the authenticated product API."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from backend.app.api.auth import router as auth_router
from backend.app.api.datasets import router as dataset_router
from backend.app.api.evaluations import router as evaluation_router
from backend.app.api.evaluators import router as evaluator_router
from backend.app.api.experiments import router as experiment_router
from backend.app.api.overview import router as overview_router
from backend.app.api.reviews import router as review_router
from backend.app.api.targets import router as target_router
from backend.app.errors import APIError, error_body
from backend.app.health import build_health_body, ping_postgres, ping_redis
from backend.app.logging import write_log
from backend.app.metrics import http_latency, http_requests
from backend.app.settings import cors_origin

app = FastAPI(title="EvalForge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[cors_origin()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(dataset_router, prefix="/api/v1")
app.include_router(target_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(evaluator_router, prefix="/api/v1")
app.include_router(overview_router, prefix="/api/v1")
app.include_router(experiment_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")


@app.middleware("http")
async def record_request(request: Request, call_next):
    import time
    import uuid

    trace_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - started
    http_requests.labels(status=str(response.status_code)).inc()
    http_latency.observe(elapsed)
    response.headers["X-Request-ID"] = trace_id
    write_log(
        "request",
        trace_id=trace_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        latency_ms=round(elapsed * 1000, 2),
    )
    return response


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(APIError)
def handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details))


@app.exception_handler(RequestValidationError)
def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"line": None, "message": error.get("msg", "Invalid request")} for error in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", "Request validation failed", details),
    )


@app.get("/health")
def health() -> JSONResponse:
    status_code, body = build_health_body(ping_postgres(), ping_redis())
    return JSONResponse(status_code=status_code, content=body)
