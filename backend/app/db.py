"""Read-only access to the shared SQLite file.

The writer (Input Orchestration) replaces the file with an atomic rename. A
pooled connection would keep reading the old, replaced inode, so every
request opens the file fresh (NullPool). The file is opened read-only at the
SQLite level on top of the read-only volume mount. The rename window can
make an open fail briefly, hence the short retry.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

_RETRIES = 3
_BACKOFF_SECONDS = 0.1


def make_engine(db_path: Path) -> Engine:
    uri = f"file:{quote(str(db_path))}?mode=ro"
    return create_engine(
        "sqlite://",
        # FastAPI opens the session in the dependency and runs sync endpoints
        # in another threadpool thread. Safe: with NullPool each connection
        # belongs to exactly one request and is never shared.
        creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False),
        poolclass=NullPool,
    )


def open_session(engine: Engine) -> Session:
    for attempt in range(_RETRIES):
        session = Session(engine)
        try:
            session.execute(text("SELECT 1 FROM GridConnectionRequests LIMIT 1"))
            return session
        except OperationalError:
            session.close()
            if attempt == _RETRIES - 1:
                raise
            time.sleep(_BACKOFF_SECONDS * (attempt + 1))
    raise AssertionError("unreachable")


def get_session(request: Request):
    session = open_session(request.app.state.engine)
    try:
        yield session
    finally:
        session.close()
