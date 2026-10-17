"""Version 2 HTTP surface: health plus the authenticated product API."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.api.auth import router as auth_router
from backend.app.api.datasets import router as dataset_router
from backend.app.api.evaluations import router as evaluation_router
from backend.app.api.targets import router as target_router
from backend.app.errors import APIError, error_body
from backend.app.health import build_health_body, ping_postgres, ping_redis

app = FastAPI(title="EvalForge", version="1.0.0")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(dataset_router, prefix="/api/v1")
app.include_router(target_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")


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
