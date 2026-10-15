from __future__ import annotations

import os
import sys
from pathlib import Path

# Locally (EG_AUTH_DEV_MODE=True) the eg-auth stub stands in for the internal
# package; in the cluster the flag is False and the real package is used.
if os.getenv("EG_AUTH_DEV_MODE", "").lower() == "true":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "local_stubs"))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app import auth, docs
from app.api import customers, reference, requests
from app.config import API_VERSION, get_db_path
from app.db import make_engine


def get_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Grid Con API",
        version=API_VERSION,
        description="Read-only API over the Silver layer of the Grid Con database "
        "(grid connection requests and customers).",
        openapi_url=docs.OPENAPI_URL,
        # Swagger UI is served offline under /api/docs (app/docs.py).
        docs_url=None,
        redoc_url=None,
    )
    app.state.engine = make_engine(db_path or get_db_path())

    @app.exception_handler(OperationalError)
    async def _db_unavailable(_: Request, __: OperationalError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Datenbank vorübergehend nicht verfügbar"},
            headers={"Retry-After": "2"},
        )

    # Liveness only, deliberately without auth and without touching the DB.
    @app.get("/api/healthz", tags=["infra"])
    def healthz() -> str:
        return "OK"

    app.include_router(auth.auth_router)
    app.include_router(requests.router)
    app.include_router(customers.router)
    app.include_router(reference.router)

    app.include_router(docs.router)
    docs.add_static_files(app)
    return app


# Start: uvicorn app.main:app (the engine opens the file only per request).
app = get_app()
