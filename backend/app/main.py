from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api import customers, evaluation, reference, requests
from app.config import API_VERSION, get_db_path
from app.db import make_engine


def get_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Grid Con API",
        version=API_VERSION,
        description="API over the Grid Con database: grid connection requests and "
        "customers (Silver, read-only), the evaluation framework, users and the "
        "collaborative evaluation (Gold; evaluators' input is written to Bronze).",
    )
    path = db_path or get_db_path()
    app.state.engine = make_engine(path)
    app.state.write_engine = make_engine(path, mode="rw")

    @app.exception_handler(OperationalError)
    async def _db_unavailable(_: Request, __: OperationalError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Datenbank vorübergehend nicht verfügbar"},
            headers={"Retry-After": "2"},
        )

    # Liveness only, deliberately without touching the DB.
    @app.get("/api/healthz", tags=["infra"])
    def healthz() -> str:
        return "OK"

    app.include_router(requests.router)
    app.include_router(customers.router)
    app.include_router(reference.router)
    app.include_router(evaluation.router)
    return app
